import os
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
                if next_step == 'APPROVED':
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
    initial_message = f"Step: {step['step']}\nDetails: {step['details']}\n\n"
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
        tempi = json.loads(output)
        tempi['STEP_ID'] = step['step']
        tempi['STEP_DETAILS'] = step['details']
        outputs.append(json.dumps(tempi))
        consolidated_report_json.append(tempi)
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
