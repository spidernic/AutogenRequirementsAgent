'''
# AutoRequirementsAgent

This is a Python-based automation tool designed to streamline the process of generating and refining requirements for any project or topic. Powered by Open Source LLMs, it leverages advanced natural language understanding to:

Generate a logical plan tailored to the given topic.
Detail requirements across functional, non-functional, integration, and operational dimensions.
Simulate a QA Manager’s review process for rigorous quality assurance.
Output requirements in JSON and text formats for seamless integration and documentation.
This tool is ideal for developers, project managers, business analysts, and system architects seeking to save time, ensure consistency, and improve the quality of their requirements gathering process

## Author Information
- **Author**: Nic Cravino
- **Email**: spidernic@me.com 
- **LinkedIn**: [Nic Cravino](https://www.linkedin.com/in/nic-cravino)
- **Date**: November 17, 2024

## License: Apache License 2.0 (Open Source)
This tool is licensed under the Apache License, Version 2.0. This is a permissive license that allows you to use, distribute, and modify the software, subject to certain conditions:

- **Freedom of Use**: Users are free to use the software for personal, academic, or commercial purposes.
- **Modification and Distribution**: You may modify and distribute the software, provided that you include a copy of the Apache 2.0 license and state any significant changes made.
- **Attribution**: Original authorship and contributions must be acknowledged when redistributing the software or modified versions of it.
- **Patent Grant**: Users are granted a license to any patents covering the software, ensuring protection from patent claims on original contributions.
- **Liability Disclaimer**: The software is provided "as is," without warranties or conditions of any kind. The authors and contributors are not liable for any damages arising from its use.

For full details, see the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
'''
import json
import yaml
import autogen

AUTOGEN_USE_DOCKER = False

gpt5_config = {
    "model": "hermes3:70b-llama3.1-q8_0",
    "base_url": "http://localhost:11434/v1",
    "api_key": "ollama",
    "cache_seed": 42,  # change the cache_seed for different trials
    "temperature": 0,
    "timeout": 220,
    "price": [0, 0],
}

# Load the prompts from the YAML file
with open('prompts.yaml', 'r') as f:
    prompts = yaml.safe_load(f)

initializer = autogen.UserProxyAgent(name="Initializer")

planningagent = autogen.AssistantAgent(
    name="planningagent",
    llm_config=gpt5_config,
    system_message=prompts['planningagent']['system_message']
)

analyst = autogen.AssistantAgent(
    name="analyst",
    llm_config=gpt5_config,
    system_message=prompts['analyst']['system_message']
)

qamanager = autogen.AssistantAgent(
    name="qamanager",
    llm_config=gpt5_config,
    system_message=prompts['qamanager']['system_message']
)

# Finalizer agent is not required for the steps, so we can omit it in the step processing

def initial_state_transition(last_speaker, groupchat):
    if last_speaker is initializer:
        return planningagent
    elif last_speaker is planningagent:
        return None

# Create the initial group chat to get the plan from the planningagent
groupchat = autogen.GroupChat(
    agents=[initializer, planningagent],
    messages=[],
    max_round=5,
    speaker_selection_method=initial_state_transition,
)

manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=gpt5_config)

# Start the chat by sending the initial message from the initializer
initializer.initiate_chat(
    manager,
    message=prompts['example_message']
)

# Extract the planningagent's output
planningagent_output = None
for msg in reversed(groupchat.messages):
    if msg['name'] == 'planningagent':
        planningagent_output = msg['content']
        break

if planningagent_output is None:
    raise ValueError("No output from planningagent.")

# Parse the planningagent's output
try:
    plan_data = json.loads(planningagent_output)
    steps = plan_data['plan']
except json.JSONDecodeError as e:
    raise ValueError(f"Failed to parse planningagent's output: {e}")

# Save the plan to JSON and TXT files
with open('generated_plan.json', 'w') as f:
    json.dump(steps, f, indent=4)

with open('generated_plan.txt', 'w') as f:
    for step in steps:
        f.write(f"STEP: {step['step']}\nDETAILS: {step['details']}\n\n")

print("Generated plan saved to 'generated_plan.json' and 'generated_plan.txt'.")


# Function to process each step
def process_step(step, outputs):
    # Reset agents for each step
    analyst.reset()
    qamanager.reset()
    # Create a group chat for the step
    def step_state_transition(last_speaker, groupchat):
        if last_speaker is None:
            # Start with the analyst
            return analyst
        elif last_speaker is step_initializer:
            return analyst
        elif last_speaker is analyst:
            return qamanager
        elif last_speaker is qamanager:
            # Parse qamanager's feedback
            feedback_msg = groupchat.messages[-1]['content']
            try:
                feedback = json.loads(feedback_msg)
                next_step = feedback.get('NEXTSTEP')
                feedback_data = feedback.get('FEEDBACK', {})  # Default to empty dict if 'FEEDBACK' doesn't exist
                score1 = feedback_data.get('OverallScore')  # Using .get() for safety
                if next_step == 'APPROVED':
                    if score1 < 5:
                        print("*" * 125)
                        print(f"Dude, the LLM is not doing Math very well, the overall score is {score1}, and is still saying APPROVE ?????")
                        print("*" * 125)
                    return None  # End the conversation
                elif next_step == 'REVISE':
                    return analyst  # Analyst needs to revise
                else:
                    return None  # End if unexpected
            except json.JSONDecodeError:
                # If cannot parse, end the conversation
                return None
        else:
            return None  # End if unexpected

    # Start the group chat with the step details
    # initial_message = f"Step: {step['step']}\nDetails: {step['details']}\n\n"
    initial_message = json.dumps({
    "Step": step["step"],
    "Details": step["details"]
}, indent=4)
    # Use a temporary initializer to send the initial message
    step_initializer = autogen.UserProxyAgent(name="StepInitializer")

    step_groupchat = autogen.GroupChat(
        agents=[step_initializer, analyst, qamanager],
        messages=[],
        max_round=10,
        speaker_selection_method=step_state_transition,
    )

    step_manager = autogen.GroupChatManager(groupchat=step_groupchat, llm_config=gpt5_config)

    # Run the group chat
    step_initializer.initiate_chat(
        step_manager,
        message=initial_message
    )

    # Collect the approved output from the analyst
    messages = step_groupchat.messages
    # Find the last message from analyst before approval
    analyst_output = None
    for i in range(len(messages)):
        msg = messages[i]
        if msg['name'] == 'analyst':
            analyst_output = msg['content']
            # Check if the next message is from qamanager with APPROVED
            if i + 1 < len(messages):
                next_msg = messages[i + 1]
                if next_msg['name'] == 'qamanager':
                    try:
                        feedback = json.loads(next_msg['content'])
                        if feedback.get('NEXTSTEP') == 'APPROVED':
                            return analyst_output.strip()
                    except json.JSONDecodeError:
                        continue
    return None  # If no approved output found

# Process each step and collect outputs
outputs = []
consolidated_report_json = []
for step in steps:
    output = process_step(step, outputs)
    if output:
        # Step 0: Remove the "OUTPUT:" prefix if present. This sometimes happens depending on the MoE that looks at the item.
        if output.startswith("OUTPUT:"):
            output = output.split("OUTPUT:", 1)[1]  # Remove the prefix
        
        # Step 1: Trim whitespace
        output = output.strip()

        # Step 2: Fix templated syntax if needed
        if "{{" in output or "}}" in output:
            output = output.replace("{{", "{").replace("}}", "}")

        # Step 3: Parse the JSON
        try:
            # Fix: Handle potential extra data by splitting and parsing separately
            json_objects = output.strip().split('\n\n')  # Split on double newlines or any separator
            for json_part in json_objects:
                try:
                    parsed_data = json.loads(json_part)
                    # Process as either list or dict
                    if isinstance(parsed_data, list):
                        for item in parsed_data:
                            item['STEP_ID'] = step['step']
                            outputs.append(json.dumps(item))
                            consolidated_report_json.append(item)
                    elif isinstance(parsed_data, dict):
                        parsed_data['STEP_ID'] = step['step']
                        outputs.append(json.dumps(parsed_data))
                        consolidated_report_json.append(parsed_data)
                except json.JSONDecodeError as e:
                    print(f"JSONDecodeError in part: {e}")
                    print(f"Invalid segment causing the issue: {repr(json_part)}")

        except Exception as e:
            print(f"Unexpected error: {e}")
            print(f"Output causing the issue: {repr(output)}")

    else:
        print(f"No approved output for step: {step['step']}")

# Concatenate all outputs and save the consolidated report
consolidated_report = "\n\n".join(outputs)

# Save the report to a file
with open('consolidated_report.txt', 'w') as f:
    f.write(consolidated_report)

# Save the consolidated report to a JSON file
with open('consolidated_report.json', 'w') as f:
    json.dump(consolidated_report_json, f, indent=4)

print("Consolidated report saved to 'consolidated_report.txt' and 'consolidated_report.json'")
