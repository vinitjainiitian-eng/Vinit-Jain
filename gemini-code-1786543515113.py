import os
import re
import uuid
import fitz  # PyMuPDF
import google.generativeai as genai
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
CROPS_FOLDER = 'static/crops'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CROPS_FOLDER, exist_ok=True)

# Gemini AI Setup
# Zaroori hai: Apne server environment mein GEMINI_API_KEY set karna
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
genai.configure(api_key=GEMINI_API_KEY)

def parse_answer_key(pdf_path):
    doc = fitz.open(pdf_path)
    text = "".join([page.get_text() for page in doc])
    pattern = re.compile(r'(?:Q)?(\d+)\s*[.)\-:]\s*([A-D1-4]|[0-9]+(?:\.[0-9]+)?)', re.IGNORECASE)
    return {int(m[0]): m[1].upper() for m in pattern.findall(text)}

def process_questions_pdf(pdf_path, test_id):
    doc = fitz.open(pdf_path)
    questions_data = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_dict = page.get_text("dict")
        
        q_locations = []
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        match = re.match(r'^(?:Q\.?|Question)\s*(\d+)|(^(\d+)\.)', text, re.IGNORECASE)
                        if match:
                            q_num = int(match.group(1) or match.group(3))
                            q_locations.append({"q_num": q_num, "y0": span.get("bbox")[1]})
                            
        q_locations = sorted(q_locations, key=lambda x: x["y0"])
        
        for i, loc in enumerate(q_locations):
            q_num = loc["q_num"]
            y_start = max(0, loc["y0"] - 10)
            y_end = q_locations[i+1]["y0"] - 10 if i + 1 < len(q_locations) else page.rect.height
            
            rect = fitz.Rect(0, y_start, page.rect.width, y_end)
            pix = page.get_pixmap(clip=rect, dpi=150)
            img_filename = f"{test_id}_q{q_num}.png"
            pix.save(os.path.join(CROPS_FOLDER, img_filename))
            
            questions_data.append({
                "qNo": q_num,
                "image": f"/static/crops/{img_filename}",
                "type": "MCQ"
            })
            
    return sorted(questions_data, key=lambda x: x["qNo"])

@app.route('/api/generate-test', methods=['POST'])
def generate_test():
    if 'questions_pdf' not in request.files or 'answer_key_pdf' not in request.files:
        return jsonify({"error": "Missing PDFs"}), 400
        
    test_id = str(uuid.uuid4())[:8]
    q_path = os.path.join(UPLOAD_FOLDER, secure_filename(f"{test_id}_Q.pdf"))
    a_path = os.path.join(UPLOAD_FOLDER, secure_filename(f"{test_id}_A.pdf"))
    
    request.files['questions_pdf'].save(q_path)
    request.files['answer_key_pdf'].save(a_path)
    
    answer_key = parse_answer_key(a_path)
    questions = process_questions_pdf(q_path, test_id)
    
    for q in questions:
        q["correct_answer"] = answer_key.get(q["qNo"])
        q["verified"] = bool(q["correct_answer"])
        
    return jsonify({"testId": test_id, "duration": 180, "questions": questions, "totalQuestions": len(questions)})

@app.route('/api/analyze-performance', methods=['POST'])
def analyze_performance():
    data = request.json
    score = data.get('score')
    accuracy = data.get('accuracy')
    attempted = data.get('attempted')
    wrong = data.get('wrong')
    
    prompt = f"""
    You are an expert JEE exam mentor. Analyze this student's CBT performance:
    Score: {score}
    Accuracy: {accuracy}%
    Attempted: {attempted}
    Wrong Answers: {wrong}
    
    Provide a highly analytical, motivational, and strategic 3-point advice block for the student to improve. Keep it concise, professional, and directly actionable. Formatting: use short bullet points.
    """
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        analysis_text = response.text
    except Exception as e:
        analysis_text = "AI Analysis is currently unavailable. Please review your wrong attempts manually."
        
    return jsonify({"ai_analysis": analysis_text})

@app.route('/static/crops/<path:filename>')
def serve_crop(filename):
    return send_from_directory(CROPS_FOLDER, filename)

if __name__ == '__main__':
    # pip install flask flask-cors pymupdf werkzeug google-generativeai
    app.run(port=5000, debug=True)