from flask import Flask, render_template, request, jsonify
import logging
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
import re
import json
import os
from werkzeug.utils import secure_filename
from docx import Document
import PyPDF2
import tempfile
import time

# Replace with your actual API key
api_key = os.environ.get("API_KEY")  # Replace this with your API key
  # Replace this with your API key

app = Flask(__name__)

# Configure the Google Generative AI API
genai.configure(api_key=api_key)

# Generation configurations
generation_config = GenerationConfig(
    temperature=0.9,
    top_p=1,
    top_k=1,
    max_output_tokens=2048,
    candidate_count=1
)

# Initialize the model for flowchart generation
model = genai.GenerativeModel('gemini-1.5-flash')

# Configure upload folder and allowed extensions
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx'}

# In-memory storage for the current flowchart data (replace with a database for persistence)
current_flowchart_data = {"nodes": [], "edges": []}
is_chart_modifying = False  # flag to prevent concurrent modifications

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():  # Only include non-empty paragraphs
            full_text.append(para.text)
    return '\n'.join(full_text)

def extract_text_from_pdf(file_path):
    with open(file_path, 'rb') as f:
        pdfReader = PyPDF2.PdfReader(f)
        full_text = []
        for page in pdfReader.pages:
            text = page.extract_text()
            if text.strip():  # Only include non-empty pages
                full_text.append(text)
    return '\n'.join(full_text)

def clean_and_validate_json(text):
    """Clean and validate JSON from the model's response."""
    json_match = re.search(r'\{[\s\S]*\}', text)
    if not json_match:
        return None

    json_str = json_match.group()

    json_str = re.sub(r'```json\s*', '', json_str)
    json_str = re.sub(r'```\s*$', '', json_str)
    json_str = json_str.strip()

    try:
        json_data = json.loads(json_str)

        if not all(key in json_data for key in ['nodes', 'edges']):
            return None

        for node in json_data['nodes']:
            if not all(key in node for key in ['id', 'label','level']):
                return None
            node['shape'] = node.get('shape', 'box')
            node['level'] = node.get('level', 0)
            node['order'] = node.get('order', 1)

        for edge in json_data['edges']:
            if not all(key in edge for key in ['from', 'to']):
                return None
            edge['order'] = edge.get('order', 1)

        return json_data
    except json.JSONDecodeError:
        return None

def generate_flowchart(topic, chart_type, animation, detail_level, document_text=None):
    max_text_length = 4000
    if document_text:
        topic_prompt = f"Generate a hierarchical {'mind map' if chart_type == 'mind_map' else 'flowchart'} based on this content:\n\n{document_text}\n\n"
    else:
        topic_prompt = f"Generate a hierarchical {'mind map' if chart_type == 'mind_map' else 'flowchart'} for: \"{topic}\".\n\n"

    prompt = topic_prompt + f"""
Please create a {'mind map' if chart_type == 'mind_map' else 'flowchart'} that is {'animated' if animation == 'animated' else 'static'} and {'simple' if detail_level == 'simple' else 'normal' if detail_level == 'normal' else 'detailed'}.
The root node for the hierarchy must be the main topic provided, and must have level 0, sub nodes must have level = 1 and sub-sub nodes must have level = 2, and all edges must follow the hierarchy of the levels specified.

Output a JSON object with this exact structure:
{{
    "nodes": [
        {{"id": 1, "label": "Start", "shape": "ellipse", "level": 0, "order": 1}},
        {{"id": 2, "label": "Process", "shape": "box", "level": 1, "order": 2}}
    ],
    "edges": [
        {{"from": 1, "to": 2, "order": 1}}
    ]
}}

Rules:
1. Use only these shapes: "ellipse", "box", "diamond", "hexagon", "circle"
2. Each node must have a unique integer id
3. Level 0 is root, increasing for each sub-level
4. Include order for animation sequence
5. Keep labels clear and concise
6. Maximum 20 nodes for simple, 35 for normal, 50 for detailed
7. Output ONLY the JSON, no other text"""

    try:
        response = model.generate_content(prompt)
        flowchart_data = clean_and_validate_json(response.text)

        if flowchart_data is None:
            return {"error": "Invalid JSON structure", "raw_response": response.text}

        # Assign sequential IDs if they are missing
        if not all('id' in node for node in flowchart_data['nodes']):
            for i, node in enumerate(flowchart_data['nodes']):
                node['id'] = i + 1

        return flowchart_data
    except Exception as e:
        return {"error": f"Error generating flowchart: {str(e)}"}

def modify_flowchart(current_data, prompt, chart_type):
    """Modifies the current flowchart based on a user prompt."""
    current_data_str = json.dumps(current_data)
    prompt_text = f"""Given the current {'mind map' if chart_type == 'mind_map' else 'flowchart'} data:\n\n{current_data_str}\n\nModify it according to the following prompt: \"{prompt}\".
The output should be a JSON object with the same structure as before, representing the updated {'mind map' if chart_type == 'mind_map' else 'flowchart'}. Ensure that the node and edge IDs remain unique and consistent where applicable. The node levels must be set such that root is always level 0, and children must be 1 or 2 or more (hierarchical). Ensure that the edges follow this node level hierarchy.

Output ONLY the JSON, no other text."""

    try:
        response = model.generate_content(prompt_text)
        modified_data = clean_and_validate_json(response.text)

        if modified_data is None:
            return {"error": "Invalid JSON structure from modification", "raw_response": response.text}

        # Initialize with existing ids
        nodes_mapping = {node['id']:node for node in current_data['nodes']}
        
        # Update nodes, adding new ones, keeping the existing ones
        for node in modified_data['nodes']:
            if node['id'] in nodes_mapping:
               nodes_mapping[node['id']]['label'] = node['label']
               nodes_mapping[node['id']]['shape'] = node.get('shape', 'box')
               nodes_mapping[node['id']]['level'] = node.get('level', 0)
               nodes_mapping[node['id']]['order'] = node.get('order', 1)
            else:
              # Generate a new unique ID if new node, keep the existing
               new_id = max([node['id'] for node in current_data['nodes']] or [0]) + 1
               node['id'] = new_id
               current_data['nodes'].append(node)
               nodes_mapping[new_id] = node

        # Remove nodes not in modified data
        modified_node_ids = set([node['id'] for node in modified_data['nodes']])
        current_data['nodes'] = [node for node in current_data['nodes'] if node['id'] in modified_node_ids]

        #Update edges
        edges_mapping = {}
        for edge in modified_data['edges']:
            new_edge_id = f"{edge['from']}-{edge['to']}-{time.time()}"
            edge['id'] = new_edge_id # Assign unique edge ID
            if not any((edge['from'] == old_edge['from'] and edge['to'] == old_edge['to']) for old_edge in current_data['edges']):
                 current_data['edges'].append(edge)
            edges_mapping[new_edge_id] = edge
        # Remove edges not in modified data
        current_data['edges'] = [edge for edge in current_data['edges'] if  f"{edge['from']}-{edge['to']}-{time.time()}" in edges_mapping]
        
        return current_data
    except Exception as e:
        return {"error": f"Error modifying flowchart: {str(e)}"}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_flowchart_data', methods=['POST'])
def get_flowchart_data():
    global current_flowchart_data
    try:
        data = request.form
        topic = data.get('topic', '').strip()
        chart_type = data.get('type', 'flowchart')
        animation = data.get('animation', 'static')
        detail_level = data.get('detail_level', 'normal')

        document_text = None
        file = request.files.get('file')

        if file and file.filename:
            if not allowed_file(file.filename):
                return jsonify({"error": "Unsupported file type."}), 400

            filename = secure_filename(file.filename)
            temp_fd, temp_path = tempfile.mkstemp()

            try:
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    file.save(temp_file)

                if filename.lower().endswith('.docx'):
                    document_text = extract_text_from_docx(temp_path)
                elif filename.lower().endswith('.pdf'):
                    document_text = extract_text_from_pdf(temp_path)

                if not topic and document_text:
                    topic = "Flowchart from Document"

            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        if not topic and not file:
            return jsonify({"error": "Please provide a topic or upload a document."}), 400

        flowchart_data = generate_flowchart(topic, chart_type, animation, detail_level, document_text)

        if 'error' in flowchart_data:
            return jsonify(flowchart_data), 500

        current_flowchart_data = flowchart_data # Store the generated data

        nodes = [{
            "id": node["id"],
            "label": node["label"],
            "shape": node.get("shape", "box"),
            "order": node.get("order", 1),
            "level": node.get("level", 0)
        } for node in flowchart_data.get('nodes', [])]

        edges = [{
            "from": edge["from"],
            "to": edge["to"],
            "id": f"{edge['from']}-{edge['to']}-{time.time()}",
            "order": edge.get("order", 1)
        } for edge in flowchart_data.get('edges', [])]

        nodes.sort(key=lambda x: x['order'])
        edges.sort(key=lambda x: x['order'])

        return jsonify({
            "nodes": nodes,
            "edges": edges,
            "animation": animation,
            "chart_type": chart_type
        })

    except Exception as e:
        logging.error(f"Error in get_flowchart_data: {str(e)}")
        return jsonify({"error": "An unexpected error occurred."}), 500

@app.route('/add_node', methods=['POST'])
def add_node():
    global current_flowchart_data
    data = request.get_json()
    new_node = data.get('node')
    if new_node:
        # Simple way to generate a new unique ID (can be improved)
        new_id = max([node['id'] for node in current_flowchart_data['nodes']] or [0]) + 1
        new_node['id'] = new_id
        current_flowchart_data['nodes'].append(new_node)
        return jsonify({"status": "success", "node": new_node})
    return jsonify({"status": "error", "message": "Invalid node data"}), 400

@app.route('/delete_node/<int:node_id>', methods=['DELETE'])
def delete_node(node_id):
    global current_flowchart_data
    current_flowchart_data['nodes'] = [node for node in current_flowchart_data['nodes'] if node['id'] != node_id]
    current_flowchart_data['edges'] = [edge for edge in current_flowchart_data['edges']
                                       if edge['from'] != node_id and edge['to'] != node_id]
    return jsonify({"status": "success"})

@app.route('/edit_node/<int:node_id>', methods=['PUT'])
def edit_node(node_id):
     global current_flowchart_data
     data = request.get_json()
     new_label = data.get('node').get('label')
     for node in current_flowchart_data['nodes']:
          if node['id'] == node_id:
                node['label'] = new_label
                return jsonify({"status": "success", "node": node})
     return jsonify({"status": "error", "message": "Node not found"}), 404

@app.route('/add_edge', methods=['POST'])
def add_edge():
    global current_flowchart_data
    data = request.get_json()
    new_edge = data.get('edge')
    if new_edge:
        current_flowchart_data['edges'].append(new_edge)
        return jsonify({"status": "success", "edge": new_edge})
    return jsonify({"status": "error", "message": "Invalid edge data"}), 400

@app.route('/delete_edge/<from_id>/<to_id>', methods=['DELETE'])
def delete_edge(from_id, to_id):
    global current_flowchart_data
    current_flowchart_data['edges'] = [
        edge for edge in current_flowchart_data['edges']
        if not (str(edge['from']) == from_id and str(edge['to']) == to_id)
    ]
    return jsonify({"status": "success"})

@app.route('/modify_flowchart_prompt', methods=['POST'])
def modify_flowchart_prompt():
    global current_flowchart_data, is_chart_modifying
    data = request.get_json()
    prompt = data.get('prompt')
    chart_type = data.get('chart_type', 'flowchart')
    animation = data.get('animation', 'static') # Get the animation value

    if not prompt:
        return jsonify({"status": "error", "message": "Prompt cannot be empty"}), 400

    if is_chart_modifying:
      return jsonify({"status": "error", "message": "Chart is currently being modified, please wait..."}), 400

    is_chart_modifying = True  # set flag
    try:
        modified_data = modify_flowchart(current_flowchart_data, prompt, chart_type)

        if 'error' in modified_data:
            return jsonify(modified_data), 500

         # Prepare the data for vis-network
        nodes = [{
            "id": node["id"],
            "label": node["label"],
            "shape": node.get("shape", "box"),
             "order": node.get("order", 1),
            "level": node.get("level", 0)
         } for node in current_flowchart_data.get('nodes', [])]

        edges = [{
            "from": edge["from"],
            "to": edge["to"],
            "id": f"{edge['from']}-{edge['to']}-{time.time()}",
            "order": edge.get("order", 1)
         } for edge in current_flowchart_data.get('edges', [])]

        return jsonify({
            "status": "success",
            "nodes": nodes,
            "edges": edges,
            "animation": animation,
             "chart_type": chart_type # Send back the chart type as well
        })
    except Exception as e:
       return jsonify({"error": f"Error modifying flowchart: {str(e)}"})
    finally:
      is_chart_modifying = False # clear flag

if __name__ == '__main__':
    app.run(debug=True)
