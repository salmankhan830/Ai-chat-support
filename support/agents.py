
from .gemini_client import Anthropic
from django.conf import settings
from .tools import get_order_details, get_refund_history, check_delivery_status,get_customer_risk_profile
from .event_queue import publish, DONE
#initialize the gemini client

from .models import  Message, AgentLog, Conversation
client= Anthropic(api_key=settings.GEMINI_API_KEY)

gemini_model = settings.GEMINI_MODEL

SUPPORT_SYSTEM_PROMPT = """
You are Maya, a customer support agent at CoolBreeze AC.
You help customers with issues related to their AC orders.

Your responsibilities:
- Always use your tools to gather facts before responding
- Check order details when customer mentions their order
- Check refund history before making any refund decisions
- Be empathetic but honest

Your personality:
- Friendly and professional
- Patient even when customer is angry
- Clear and concise in your replies
- No emojies

Important rules:
- Always check order details first before responding
- Never approve or deny a refund yourself
- If refund decision is needed — tell customer you are checking with your team
- Never use bold text, bullet points or any markdown formatting. Plain text only.
- Keep replies concise and conversational. Maximum 3-4 sentences. No long paragraphs.
"""

MANAGER_SYSTEM_PROMPT = """
You are a senior support manager at CoolBreeze AC.
A support agent has escalated a customer case to you for a refund decision.

Your responsibilities:
- Review the case summary carefully
- Consider the customer's refund history
- Make a fair and final refund decision
- Give a clear reason for your decision

Your decision options:
- Approve refund — if the case is genuine and within policy
- Deny refund — if the case is suspicious or outside policy
- Escalate to risk team — if you suspect fraud

Important rules:
- Be fair but firm
- Base decision on facts — not emotions
- Always give a specific reason for your decision
- Keep your response concise and professional
- Never answer "escalate to risk team"; the risk is already done for you,
"""

RISK_SYSTEM_PROMPT="""
You are a fraud risk analyst at CoolBreeze AC.
A support manager has sent you a customer profile for risk assessment.

Your job:
- Analyse the customer's order and refund patterns
- Identify suspicious behaviour
- Return a clear risk verdict

Risk levels:
- LOW — genuine customer, normal behaviour
- MEDIUM — some suspicious signals, proceed with caution
- HIGH — clear fraud pattern, recommend denial

Your response format:
- Risk Level: LOW / MEDIUM / HIGH
- Key Signals: what you found suspicious or genuine
- Recommendation: what manager should do

Important:
- Be objective — base verdict on data only
- One bad refund does not make someone fraudulent
- Look for patterns — not isolated incidents
- After using your tools, ALWAYS finish with a text verdict in this format:
RISK: LOW / MEDIUM / HIGH
REASON: one short sentence
"""

#support Tools ==> Tools schemas
support_tools=[
    {
        "name": "get_order_details",
        "description": "Fetch complete order details including status, carrier, tracking number and days since order was placed. Use this when customer mentions their order or complains about delivery",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id":{
                    "type": "integer",
                    "description": "The order ID to look up"
                }
            },
            "required" : ["order_id"]
        }

},

    {
"name": "get_refund_history",
        "description": "Get complete refund history for a user. Use this before making any refund related decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to check refund history for"
                }
            },
            "required": ["user_id"]
        }
    },

    {
"name": "check_delivery_status",
        "description": "Check current delivery status using tracking number and carrier. Use this when customer complains about delayed or missing delivery.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "The shipment tracking number"
                },
                "carrier": {
                    "type": "string",
                    "description": "The carrier name for example BlueDart or Delhivery"
                }
            },
            "required": ["tracking_number", "carrier"]
        }
    },

    {
        "name": "escalate_to_manager",
        "description": "Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "case_summary": {
                    "type": "string",
                    "description": "Complete case summary. Must include: customer user_id, order details, refund history and complaint. Format: Start with 'Customer User ID: X' on the first line."
                }
            },
            "required": ["case_summary"]
        }
    },
]

MANAGER_TOOLS= [
    {
        "name": "assess_fraud_risk",
        "description": "Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess fraud risk for"
                }
            },
            "required": ["user_id"]
        }
    }
]

RISK_TOOLS=[
    {
        "name": "get_customer_risk_profile",
        "description": "Get complete risk profile for a customer including order history, refund patterns and ratio. Use this to assess fraud risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess risk for"
                }
            },
            "required": ["user_id"]
        }
    }
]


#execute Tool -->It acts as a bridge between claude and the tools
def execute_tool(tool_name, tool_input, conversation_id=None):
    if tool_name == "get_order_details":
        return get_order_details(tool_input["order_id"])

    if tool_name == "get_refund_history":
        return get_refund_history(tool_input["user_id"])

    if tool_name == "check_delivery_status":
        return check_delivery_status(tool_input["tracking_number"], tool_input["carrier"])

    if tool_name == "escalate_to_manager":
        case_summary = tool_input["case_summary"]
        print("escalating to manager===>", case_summary)
        decision = run_manager_agent(case_summary, conversation_id)
        print("decision==>",decision)
        return decision

    if tool_name == "assess_fraud_risk":
        user_id = tool_input["user_id"]
        print("consulting risk agent for user==>", user_id)
        verdict=run_risk_agent(user_id, conversation_id)
        print("risk_verdict==>", verdict)
        return verdict

    if tool_name == "get_customer_risk_profile":
        return get_customer_risk_profile(tool_input["user_id"])


    return {"error":f"unknown tool :{tool_name}"}
#Agent Loop --> while loop that loops until the task is done
def run_support_agent(user_message, conversation_id, order_id=None, user_id=None):
    conv =Conversation.objects.get(id=conversation_id)

    conversation_messages = []
    for msg in conv.messages.order_by("created_at"):
        conversation_messages.append({
            "role":"assistant" if msg.role == "agent" else "user",
            "content":msg.content,
        })

    while True:
        response = client.messages.create(
            model=gemini_model,
            max_tokens=1024,
            system=SUPPORT_SYSTEM_PROMPT + f"\n\nContext: This conversation is about Order #{order_id}, user:{user_id}",
            tools=support_tools,
            messages=conversation_messages,
        )
        print('stop_reason==>', response.stop_reason)
        print('content==>', response.content)

        if response.stop_reason == 'tool_use':
            tool_result=[]
            for block in response.content:
                if block.type =='tool_use':
                    event = {"type": "tool_call", "message": f"calling tool {block.name} with {block.input}"}
                    publish(conversation_id, event)
                    AgentLog.objects.create(conversation=conv, event_type= "tool_call", message=f"calling tool {block.name} with {block.input}")

                    #execute Tool
                    result = execute_tool(block.name, block.input,conversation_id)
                    event = {"type": "tool_result", "message": f"calling tool {block.name} with {block.input}"}
                    publish(conversation_id, event)

                    AgentLog.objects.create(conversation=conv, event_type= "tool_result", message=f"{block.name} returned {str(result)[:200]}")
                    print("executing tool  ==>", block.name)
                    print('block.input==>', block.input)

                    tool_result.append({
                        "type":"tool_result",
                        "tool_use_id": block.id,
                        "content": str(result)
                    })

            conversation_messages.append({
            "role": "assistant",
            "content": response.content
            })
            conversation_messages.append({
                "role":"user",
                "content": tool_result
            })
        else:
            final_reply = "".join(b.text for b in response.content if b.type =="text")
            event = {"type":"final", "message": final_reply }
            publish(conversation_id, event)
            AgentLog.objects.create(conversation=conv, event_type="final", message=f"{final_reply[:200]}")

            publish(conversation_id, DONE)
            return final_reply

def run_manager_agent(case_summary, conversation_id):
    conv = Conversation.objects.get(id= conversation_id)
    event = {"type": "manager", "message": f"case received for review: {case_summary[:200]}"}
    publish(conversation_id, event)
    AgentLog.objects.create(conversation= conv, event_type="manager", message = f"case received for review: {case_summary[:200]}")
    manager_messages = [
        {
        'role':"user",
        'content':case_summary
        }
    ]

    while True:
        response = client.messages.create(
            model=gemini_model,
            max_tokens=1024,
            system=MANAGER_SYSTEM_PROMPT,
            tools=MANAGER_TOOLS,
            messages=manager_messages,

        )
        if response.stop_reason == 'tool_use':
            tool_result=[]
            for block in response.content:
                if block.type == 'tool_use':
                    event = {"type": "manager", "message": "calling risk agent for fraud assessment..."}
                    publish(conversation_id, event)
                    AgentLog.objects.create(conversation= conv, event_type = "manager", message = "calling risk agent for fraud assessment...")
                    result = execute_tool(block.name, block.input,conversation_id)
                    tool_result.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result)
                    })
            manager_messages.append({
                "role":"assistant",
                "content": response.content
            })
            manager_messages.append({
                "role":"user",
                "content":tool_result,
            })
        else:
            final_reply = "".join(b.text for b in response.content if b.type == "text")
            event = {"type": "manager", "message": f"Decision: {final_reply[:200]}"}
            publish(conversation_id, event)

            AgentLog.objects.create(conversation=conv, event_type="manager", message=f"Decision: {final_reply[:200]}")
            return final_reply



def run_risk_agent(user_id, conversation_id):
    conv = Conversation.objects.get(id= conversation_id)
    event = {"type": "risk", "message": f"starting fraud assessment for user {user_id}"}
    publish(conversation_id, event)
    #log risk assessment
    AgentLog.objects.create(conversation = conv, event_type="risk", message = f"starting fraud assessment for user {user_id}")
    risk_messages = [
        {"role":"user",
         "content":f"Please assess the fraud risk for user ID {user_id}.use your tool to get their profile and return a verdict."
         }
    ]

    while True:
        response = client.messages.create(
            model=gemini_model,
            max_tokens=1024,
            system=RISK_SYSTEM_PROMPT,
            tools=RISK_TOOLS,
            messages=risk_messages,
        )
        if response.stop_reason == 'tool_use':
            tool_result=[]
            for block in response.content:
                if block.type == 'tool_use':
                    event = {"type": "risk", "message": f"Calling {block.name} to get customer risk profile"}
                    publish(conversation_id, event)
                    AgentLog.objects.create(conversation=conv, event_type="risk",message=f"Calling {block.name} to get customer risk profile")

                    result = execute_tool(block.name, block.input, conversation_id)

                    tool_result.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result)
                    })
                risk_messages.append({
                    "role":"assistant",
                    "content": response.content
                })
                risk_messages.append({
                    "role": "user",
                    "content": tool_result,
                })
            else:
                final_reply = "".join(b.text for b in response.content if b.type == "text")
                event = {"type": "risk", "message": f"Verdict: {final_reply[:200]}"}
                publish(conversation_id, event)
                AgentLog.objects.create(conversation=conv, event_type="risk",message=f"Verdict: {final_reply[:200]}")
                # print("risk response==>", response.content, response.stop_reason)
                return final_reply
