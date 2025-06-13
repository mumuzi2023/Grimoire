import requests
import json
import time

ONEBOT_API_URL = "http://127.0.0.1:3000"  # Your API URL
TARGET_GROUP_ID = "796119994"  # Your Target Group ID
ACCESS_TOKEN = None  # Your Access Token, if any


def send_onebot_request(action: str, params: dict):
    endpoint = f"{ONEBOT_API_URL}/{action}"
    headers = {"Content-Type": "application/json"}
    if ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"

    print(f"Sending action '{action}' with payload: {json.dumps(params, indent=2, ensure_ascii=False)}")
    try:
        response = requests.post(endpoint, headers=headers, json=params)
        response.raise_for_status()
        response_json = response.json()
        print(f"Success: {json.dumps(response_json, indent=2, ensure_ascii=False)}")
        return response_json
    except Exception as e:
        print(f"Error sending action '{action}': {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Error details: {e.response.text}")
        return None


def send_nested_forward_message(group_id: str, nodes: list):
    params = {"group_id": int(group_id) if str(group_id).isdigit() else group_id, "messages": nodes}
    return send_onebot_request("send_group_forward_msg", params)


if __name__ == "__main__":
    print("--- Minimal Multi-Level Nested Forwarded Message ---")

    # Level 2 (Innermost) Node Content
    level2_node_content = {
        "type": "node",
        "data": {
            "user_id": 10003,
            "nickname": "Deep Inner Voice",
            "content": "This is the deepest level message!"
        }
    }

    # Level 1 (Inner) Node, its content will be the Level 2 node
    level1_node = {
        "type": "node",
        "data": {
            "user_id": 10002,
            "nickname": "Inner Layer",
            # Embedding the level2_node_content directly as the content
            "content": level2_node_content
        }
    }

    # Level 0 (Outer) Nodes
    outer_forward_nodes = [
        {
            "type": "node",
            "data": {
                "user_id": 2497440459,
                "nickname": "Outer Layer Narrator",
                "content": "This is the first message of the outer layer."
            }
        },
        {  # This node's content will be the Level 1 node structure
            "type": "node",
            "data": {
                "user_id": 2497440459,
                "nickname": "Nesting Point",
                # Embedding the level1_node directly as the content
                "content": level1_node
            }
        },
        {
            "type": "node",
            "data": {
                "user_id": 2497440459,
                "nickname": "Outer Layer Narrator",
                "content": "This is a message after the nested structure."
            }
        }
    ]

    if not TARGET_GROUP_ID or TARGET_GROUP_ID == "YOUR_GROUP_ID_HERE":
        print("Please set a valid 'TARGET_GROUP_ID'.")
    else:
        print(f"Attempting to send multi-level nested message to group: {TARGET_GROUP_ID}")
        send_nested_forward_message(TARGET_GROUP_ID, outer_forward_nodes)
        print("\n--- Attempt Finished. Check your QQ group. ---")