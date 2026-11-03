#Demonstration of CREATE then GET through the Kafka client.

import json
from uuid import uuid4

from hw7_authentication import send_request


def run_demo():
    #send_request creates one correlation ID, sends CREATE, and logs it.
    #worker logs processing and reply
    #send_request logs the matched response.
    created = send_request("CREATE_RECALL_NOTICE", {
        "name": "Spinach recall",
        "description": "Possible contamination in batch LOT-101",
        "unique_code": f"RECALL_{uuid4().hex[:12].upper()}",
        "quantity": 25,
        "related_grocery_recall_notice_id": 1,
    })
    if not created["success"]:
        raise RuntimeError(created["error"])
    # extract the generated UUID and send GET through the same client.
    retrieved = send_request("GET_RECALL_NOTICE", {
        "grocery_recall_notice_id": created["grocery_recall_notice_id"],
    })
    if not retrieved["success"]:
        raise RuntimeError(retrieved["error"])
    #send_request only returns a response matching its correlation ID.
    # Confirm GET returned the created entity and display its complete data.
    assert retrieved["grocery_recall_notice"]["recall_notice_id"] == created["recall_notice_id"]
    print(json.dumps(retrieved, indent=2))


if __name__ == "__main__":
    run_demo()
