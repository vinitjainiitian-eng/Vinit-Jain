import os
import re
import io
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader
from google import genai
from google.genai import types

app = FastAPI()

# Allow Frontend to talk to Backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, put your Vercel link here
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API Key missing")
    return genai.Client(api_key=api_key)

@app.get("/")
def home():
    return {"status": "Backend is running!"}

# --- PDF PARSER ---
@app.post("/api/process-pdfs")
async def process_pdfs(question_pdf: UploadFile = File(...), answer_pdf: UploadFile = File(None)):
    try:
        # Read Question PDF
        q_bytes = await question_pdf.read()
        q_reader = PdfReader(io.BytesIO(q_bytes))
        q_text = "\n".join([page.extract_text() or "" for page in q_reader.pages])

        questions = []
        q_blocks = re.split(r'\n(?=(?:Q(?:uestion)?\s*\d+|\d+[\.\)]))\s*', q_text, flags=re.IGNORECASE)
        
        current_subject = "Physics"
        
        for block in q_blocks:
            block = block.strip()
            if not block: continue
                
            if re.search(r'chemistry', block, re.IGNORECASE): current_subject = "Chemistry"
            elif re.search(r'math', block, re.IGNORECASE): current_subject = "Mathematics"

            q_match = re.match(r'^(?:Q(?:uestion)?\s*)?(\d+)[\.\)]?\s*(.*)', block, re.DOTALL | re.IGNORECASE)
            if not q_match: continue
                
            q_num = int(q_match.group(1))
            content = q_match.group(2).strip()

            option_matches = re.findall(r'(?:[\(\[]?([A-D1-4])[\)\.]\]?)\s*([^\n]+)', content)
            q_type = "MCQ" if len(option_matches) >= 4 else "NAT"
            
            options = [opt[1].strip() for opt in option_matches[:4]] if q_type == "MCQ" else []
            clean_text = content.split('(A)')[0].split('(1)')[0].strip() if q_type == "MCQ" else content

            questions.append({
                "id": q_num, "subject": current_subject, "type": q_type,
                "text": clean_text, "options": options, "answer": "FLAGGED"
            })

        # Process Answer Key if provided
        if answer_pdf and answer_pdf.filename:
            a_bytes = await answer_pdf.read()
            a_reader = PdfReader(io.BytesIO(a_bytes))
            a_text = "\n".join([page.extract_text() or "" for page in a_reader.pages])
            
            ans_matches = re.findall(r'(?:Q)?(\d+)[\s:\-\.=]+([A-D1-4]|-?\d+(?:\.\d+)?)', a_text, re.IGNORECASE)
            answers_dict = {int(k): v.strip().upper() for k, v in ans_matches}
            
            for q in questions:
                if q["id"] in answers_dict:
                    raw_ans = answers_dict[q["id"]]
                    if q["type"] == "MCQ" and raw_ans in ['A','B','C','D']:
                        q["answer"] = str(ord(raw_ans) - ord('A') + 1)
                    else:
                        q["answer"] = raw_ans

        return {"success": True, "total_extracted": len(questions), "questions": questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- AI ANALYSIS ---
class AnalysisData(BaseModel):
    score: int
    data: dict

@app.post("/api/analyze-test")
async def analyze_test(data: AnalysisData, client: genai.Client = Depends(get_gemini_client)):
    prompt = f"Analyze this JEE Mock Test Data. Score: {data.score}. Data: {data.data}. Give a short JSON response with 'summary' and 'weakness'."
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return response.text
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
          
