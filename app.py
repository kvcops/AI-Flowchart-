from flask import Flask, request, render_template, jsonify
import google.generativeai as genai
import os
import json
import re

app = Flask(__name__)

api_key = os.environ.get("API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

def generate_flowchart(topic):
    prompt = f"""
    Generate a detailed flowchart or mind map for the topic/algorithm: "{topic}".

    The output should be in JSON format with the following structure:

    {{
        "nodes": [
            {{"id": 1, "label": "Start", "level": 0, "shape": "ellipse"}},
            {{"id": 2, "label": "Step 1", "level": 1, "shape": "box"}}
        ],
        "edges": [
            {{"from": 1, "to": 2}}
        ]
    }}

    **Important Guidelines:**

    1. **Unique IDs:**  Ensure each node has a unique integer `id`.
    2. **Descriptive Labels:**  Provide clear and concise labels for each node (`"label"`).
    3. **Hierarchical Levels:**  Use `level` to indicate the hierarchy (0 for the top level, 1 for the next level, etc.).
    4. **Node Shapes:**  Choose appropriate shapes using the `shape` field:
        - "ellipse": For start/end nodes
        - "box": For process steps
        - "diamond": For decision nodes
        - "hexagon": For preparation steps
        - "circle": For connectors (if needed)
    5. **Edges:**  Specify connections using the `from` and `to` fields in the `edges` array.
    6. **Flow:** Ensure a logical and easy-to-follow flow.
    7. **Comprehensiveness:**  Include all major steps or concepts.
    8. **Spacing:** Use a minimum horizontal spacing of 200 and vertical spacing of 150 between nodes to prevent overlapping. 
    9. **No Isolated Nodes:** All nodes should be connected in a coherent structure.
    10. **Clear Visualization:** The flowchart/mind map should be visually clear and easily understandable. Avoid overly complex visualizations. 
    11. **Avoid Overlapping:**  Make sure nodes don't overlap with each other (at any level) due to their size or placement.
    12. **Spacing Considerations:** Adjust the spacing between nodes based on the node size and content to ensure adequate readability.

    **Output Format:**
    - Output only the JSON structure, no additional text or explanations.
    - Ensure that the output is correctly formatted and adheres to the provided JSON structure.
    
    **Example (Simple Algorithm):**
    
    {{
        "nodes": [
            {{"id": 1, "label": "Start", "level": 0, "shape": "ellipse"}},
            {{"id": 2, "label": "Get input", "level": 1, "shape": "box"}},
            {{"id": 3, "label": "Process input", "level": 1, "shape": "box"}},
            {{"id": 4, "label": "Output results", "level": 1, "shape": "box"}},
            {{"id": 5, "label": "End", "level": 0, "shape": "ellipse"}}
        ],
        "edges": [
            {{"from": 1, "to": 2}},
            {{"from": 2, "to": 3}},
            {{"from": 3, "to": 4}},
            {{"from": 4, "to": 5}}
        ]
    }}
    """

    response = model.generate_content(prompt)
    print("Raw API response:", response.text)  # For debugging
    
    # Try to extract a JSON object from the response
    json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
    if json_match:
        try:
            flowchart_data = json.loads(json_match.group())
            return flowchart_data
        except json.JSONDecodeError:
            return {"error": "Invalid JSON structure", "raw_response": response.text}
    else:
        return {"error": "No JSON object found in the response", "raw_response": response.text}

@app.route('/get_flowchart_data', methods=['POST'])
def get_flowchart_data():
    topic = request.json['topic']
    flowchart_data = generate_flowchart(topic)
    
    # Prepare the data for vis-network
    nodes = [{"id": node["id"], "label": node["label"], "shape": node.get("shape", "box")} for node in flowchart_data.get('nodes', [])]
    edges = [{"from": edge["from"], "to": edge["to"]} for edge in flowchart_data.get('edges', [])]
    
    return jsonify({"nodes": nodes, "edges": edges, "error": flowchart_data.get("error"), "raw_response": flowchart_data.get("raw_response")})


if __name__ == '__main__':
    app.run(debug=True)
