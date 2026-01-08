import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import base64
import fitz  # or PyMuPDF
import re
import json
import time
import traceback

import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

# Try Ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
    print("✓ Ollama Python package loaded successfully")
except Exception as e:
    print(f"⚠ Ollama Python package not available: {e}")
    OLLAMA_AVAILABLE = False


# CONFIGURATION
OLLAMA_MODEL = "deepseek-r1:8b"

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# Utility Functions
def clean_text(text):
    """Clean and normalize text while preserving newlines"""
    if not text:
        return ""
    # Replace multiple spaces/tabs with single space, but keep newlines
    text = re.sub(r'[ \t]+', ' ', text)
    # limit consecutive newlines to 2
    text = re.sub(r'\n\s*\n', '\n', text)
    return text.strip()

def extract_text_from_pdf_bytes(file_bytes):
    """Extract text from PDF bytes"""
    try:
        text = ""
        # Open PDF from bytes
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n"
        doc.close()
        return clean_text(text)
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""

def extract_text_from_pdf(file_path):
    """Extract text from PDF file path"""
    try:
        text = ""
        with fitz.open(file_path) as doc:
            for page in doc:
                text += page.get_text("text") + "\n"
        return clean_text(text)
    except Exception as e:
        print(f"PDF extraction error: {e}")
        return ""

def is_potential_name(text):
    """Check if text could be a person's name"""
    if not text or len(text) < 3 or len(text) > 50:
        return False
    
    # Remove special characters except spaces and hyphens
    clean_text = re.sub(r'[^A-Za-z\s\-]', '', text).strip()
    
    # Check if it contains common non-name words
    non_name_indicators = [
        'resume', 'cv', 'curriculum', 'vitae', 'linkedin', 'github',
        'email', 'phone', 'mobile', 'contact', 'address', 'summary',
        'experience', 'education', 'skills', 'projects', 'certifications',
        'objective', 'profile', 'internship', 'trainings'
    ]
    
    if any(indicator in clean_text.lower() for indicator in non_name_indicators):
        return False
    
    # Should contain at least 2 words
    words = clean_text.split()
    if len(words) < 2 or len(words) > 4:
        return False
    
    # Most names have words starting with capital letters
    capital_words = sum(1 for word in words if word and word[0].isupper())
    if capital_words < len(words) * 0.7:  # At least 70% should be capitalized
        return False
    
    # Exclude lines that look like job titles
    job_title_indicators = [
        'engineer', 'developer', 'analyst', 'specialist', 'manager',
        'director', 'consultant', 'associate', 'assistant', 'officer'
    ]
    
    if any(indicator in clean_text.lower() for indicator in job_title_indicators):
        return False
    
    return True

def extract_name_from_line(line):
    """Extract name from a single line of text"""
    # Remove any markdown, bullets, etc.
    line = re.sub(r'^[#\*\-•]\s*', '', line).strip()
    
    # Remove contact info patterns
    line = re.sub(r'[\+\d\s\-\(\)]{10,}', '', line)  # Remove phone numbers
    line = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '', line)  # Remove emails
    line = re.sub(r'linkedin\.com/[^\s]+', '', line, flags=re.IGNORECASE)  # Remove LinkedIn
    line = re.sub(r'github\.com/[^\s]+', '', line, flags=re.IGNORECASE)  # Remove GitHub
    
    # Clean up the line
    line = line.strip()
    
    # If the line still has content and looks like a name
    if line and is_potential_name(line):
        return format_name(line)
    
    return None

def format_name(name):
    """Format name to proper title case"""
    # Remove any special characters except letters, spaces, and hyphens
    name = re.sub(r'[^A-Za-z\s\-]', ' ', name)
    # Convert to title case
    name = name.title()
    # Clean up multiple spaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def extract_name_from_text(text):
    """Extract candidate name from resume text using robust helper functions"""
    try:
        # Split text into lines
        lines = text.strip().split('\n')
        
        # Check the first 20 lines for a valid name using the helper function
        for line in lines[:20]:
            # extract_name_from_line handles cleaning and validation
            name = extract_name_from_line(line)
            if name:
                return name
        
        # If nothing found, return "Candidate"
        return "Candidate"
        
    except Exception as e:
        print(f"Name extraction from text failed: {e}")
        return "Candidate"

def extract_contact_info(file_bytes_or_path):
    """Extract contact information from PDF bytes or path"""
    try:
        # Extract text
        if isinstance(file_bytes_or_path, bytes):
            text = extract_text_from_pdf_bytes(file_bytes_or_path)
        else:
            text = extract_text_from_pdf(file_bytes_or_path)
        
        # Extract name from text
        name = extract_name_from_text(text)
        print(f"🔍 Extracted name: '{name}'")  # Debug line
        
        # If name is still generic, try to find email and extract from it
        if name == "Candidate" or "Candidate" in name:
            # Look for email in the text
            email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
            emails = re.findall(email_pattern, text)
            if emails:
                email = emails[0]
                # Try to extract name from email (before @)
                email_name = email.split('@')[0]
                # Remove numbers and special chars
                email_name = re.sub(r'[\d\._-]+', ' ', email_name)
                email_name = email_name.title().strip()
                if email_name and len(email_name.split()) >= 2:
                    name = email_name
                    print(f"🔍 Extracted name from email: '{name}'")
        
        info = {
            "name": name,
            "emails": [],
            "phones": [],
            "linkedin": [],
            "github": []
        }
        
        # Extract emails
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        info["emails"] = list(set(re.findall(email_pattern, text)))
        
        # Extract LinkedIn
        linkedin_pattern = r'(?:https?://)?(?:www\.)?linkedin\.com/(?:in|pub|company)/[a-zA-Z0-9_-]+'
        info["linkedin"] = list(set(re.findall(linkedin_pattern, text, re.IGNORECASE)))
        
        # Extract GitHub
        github_pattern = r'(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9_-]+'
        info["github"] = list(set(re.findall(github_pattern, text, re.IGNORECASE)))
        
        # Extract phone numbers
        phone_pattern = r'[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}'
        info["phones"] = list(set(re.findall(phone_pattern, text)))
        
        return info
        
    except Exception as e:
        print(f"Contact info extraction error: {e}")
        return {
            "name": "Candidate",
            "emails": [],
            "phones": [],
            "linkedin": [],
            "github": []
        }

def analyze_with_ollama_complete(text, contact_info):
    """Complete analysis using Ollama - extracts everything from resume"""
    if not OLLAMA_AVAILABLE:
        return get_basic_fallback(text)
    
    try:
        # Comprehensive prompt for complete analysis
        prompt = f"""You are an expert career coach and resume analyzer. Analyze this resume completely and provide detailed insights.
        RESUME CONTENT:
        {text[:2500]}

        CANDIDATE INFORMATION:
        - Name: {contact_info['name']}
        - Email: {', '.join(contact_info['emails'][:2]) if contact_info['emails'] else 'Not provided'}
        - LinkedIn: {', '.join(contact_info['linkedin'][:1]) if contact_info['linkedin'] else 'Not provided'}
        - GitHub: {', '.join(contact_info['github'][:1]) if contact_info['github'] else 'Not provided'}

        Please analyze this resume and provide COMPLETE insights including:

        1. Extract ALL technical skills mentioned in the resume (programming languages, frameworks, tools, etc.)
        2. Extract ALL soft skills mentioned or implied
        3. Identify the candidate's experience level (entry-level, mid-level, senior, etc.)
        4. Suggest suitable job titles based on the resume content
        5. Analyze strengths and weaknesses
        6. Provide actionable recommendations
        7. Give an overall assessment

        IMPORTANT: Extract skills and job titles ONLY from the resume content. Do not add generic skills or titles.

        Return your analysis in this EXACT JSON format:
        {{
            "overall_assessment": {{
                "score": 0-100,
                "grade": "A/B/C/D/F",
                "summary": "One sentence overall assessment",
                "experience_level": "Entry-level/Mid-level/Senior/Executive"
            }},
            "extracted_skills": {{
                "technical_skills": ["skill1", "skill2", "skill3"],
                "soft_skills": ["skill1", "skill2", "skill3"],
                "tools_platforms": ["tool1", "tool2", "tool3"]
            }},
            "suggested_job_titles": [
                {{"title": "Job Title 1", "confidence": 0-100, "reason": "Why this title fits"}},
                {{"title": "Job Title 2", "confidence": 0-100, "reason": "Why this title fits"}},
                {{"title": "Job Title 3", "confidence": 0-100, "reason": "Why this title fits"}}
            ],
            "strengths_analysis": [
                {{"title": "Strength title", "description": "Detailed explanation", "evidence": "From resume"}}
            ],
            "weaknesses_analysis": [
                {{"title": "Weakness title", "description": "What needs improvement", "suggestion": "How to improve"}}
            ],
            "recommendations": [
                {{"priority": "High/Medium/Low", "action": "Specific action item", "timeline": "When to complete"}}
            ],
            "career_advice": "Personalized career advice based on the resume content"
        }}

        Rules:
        1. Only extract skills and titles that are actually mentioned or clearly implied in the resume
        2. Be specific and evidence-based
        3. Provide actionable feedback
        4. Consider the candidate's apparent experience level
        5. Focus on practical, implementable advice"""

        print(f"🤖 Analyzing resume with {OLLAMA_MODEL}...")
        start_time = time.time()
        
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a precise, analytical career coach who extracts information only from provided content."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            options={
                'temperature': 0.2,  # Lower temperature for more precise extraction
                'top_p': 0.8,
                'num_predict': 2000
            }
        )
        
        elapsed = time.time() - start_time
        print(f"✓ Analysis completed in {elapsed:.1f}s")
        
        content = response['message']['content']
        
        # Try to extract JSON
        try:
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                analysis = json.loads(json_str)
                analysis["source"] = f"Ollama ({OLLAMA_MODEL})"
                analysis["response_time"] = f"{elapsed:.1f}s"
                return analysis
        except json.JSONDecodeError as e:
            print(f"⚠ JSON parsing error: {e}")
            print(f"First 500 chars of response: {content[:500]}")
        
        # Fallback
        return get_enhanced_fallback(text, contact_info)
        
    except Exception as e:
        print(f"❌ Ollama analysis failed: {e}")
        traceback.print_exc()
        return get_enhanced_fallback(text, contact_info)

def get_enhanced_fallback(text, contact_info):
    """Fallback analysis when Ollama fails"""
    word_count = len(text.split())
    
    return {
        "overall_assessment": {
            "score": 65,
            "grade": "C+",
            "summary": "Resume analysis completed with basic assessment",
            "experience_level": "To be determined"
        },
        "extracted_skills": {
            "technical_skills": ["Skills analysis unavailable"],
            "soft_skills": ["Please check AI response"],
            "tools_platforms": []
        },
        "suggested_job_titles": [
            {
                "title": "Technical Professional",
                "confidence": 60,
                "reason": "Based on resume content analysis"
            }
        ],
        "strengths_analysis": [
            {
                "title": "Content Available",
                "description": "Resume contains detailed information",
                "evidence": f"{word_count} words analyzed"
            }
        ],
        "weaknesses_analysis": [
            {
                "title": "AI Analysis Limited",
                "description": "Could not perform detailed AI analysis",
                "suggestion": "Try again or check Ollama connection"
            }
        ],
        "recommendations": [
            {
                "priority": "Medium",
                "action": "Review resume formatting",
                "timeline": "1 week"
            }
        ],
        "career_advice": "Consider having your resume reviewed by a career coach for detailed feedback.",
        "source": "Fallback Analysis"
    }

def get_basic_fallback(text):
    """Basic fallback when Ollama is not available"""
    return {
        "overall_assessment": {
            "score": 50,
            "grade": "C",
            "summary": "Basic resume review completed",
            "experience_level": "Not analyzed"
        },
        "extracted_skills": {
            "technical_skills": ["Please enable Ollama for skill extraction"],
            "soft_skills": ["AI analysis required"],
            "tools_platforms": []
        },
        "suggested_job_titles": [
            {
                "title": "General Professional Role",
                "confidence": 50,
                "reason": "Basic resume content present"
            }
        ],
        "strengths_analysis": [
            {
                "title": "Resume Submitted",
                "description": "Successfully uploaded and processed resume",
                "evidence": "File processed successfully"
            }
        ],
        "weaknesses_analysis": [
            {
                "title": "AI Analysis Unavailable",
                "description": "Ollama is not available for detailed analysis",
                "suggestion": "Install and run Ollama for complete analysis"
            }
        ],
        "recommendations": [
            {
                "priority": "High",
                "action": "Enable Ollama for better analysis",
                "timeline": "Immediate"
            }
        ],
        "career_advice": "For detailed resume analysis, please ensure Ollama is installed and running.",
        "source": "Basic System Analysis"
    }

def analyze_resume_from_bytes(file_bytes):
    """Analyze resume from bytes"""
    try:
        # Extract text
        text = extract_text_from_pdf_bytes(file_bytes)
        if len(text) < 100:
            return {"error": "Resume text too short or unreadable"}
        
        # Extract contact info
        contact_info = extract_contact_info(file_bytes)
        
        # AI analysis
        analysis = analyze_with_ollama_complete(text, contact_info)
        
        return {
            "text": text[:2000],
            "contact_info": contact_info,
            "analysis": analysis,
            "stats": {
                "word_count": len(text.split()),
                "char_count": len(text),
                "contact_completeness": sum(1 for k, v in contact_info.items() 
                                            if v and k != 'summary' and (isinstance(v, list) and len(v) > 0 or not isinstance(v, list)))
            }
        }
        
    except Exception as e:
        print(f"Analysis error: {e}")
        traceback.print_exc()
        return {"error": str(e)}


# Dash Application
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.FLATLY,
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"
    ],
    suppress_callback_exceptions=True
)

app.title = "AI Resume Analyzer"

# Custom CSS will be loaded from assets/style.css
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
    </head>
    <body style="background-color: #0B0B10; color: #EAEAF0;">
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''


# Layout
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col([
            html.Div([
                html.H1("🤖 AI Resume Analyzer", className="text-light mb-3"),
                html.P("AI-powered resume analysis with detailed career insights", className="text-ghost-grey lead mb-4"),
                html.Div([
                    dbc.Badge("Powered by Ollama AI", color="primary", className="me-2 px-3 py-2"),
                    dbc.Badge(f"Model: {OLLAMA_MODEL}", color="info", className="px-3 py-2")
                ])
            ], className="text-center py-5")
        ], width=12)
    ], className="gradient-header rounded-bottom-4 mb-5"),
    
    # Main Content
    dbc.Row([
        dbc.Col([
            # Upload Section
            dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.I(className="fas fa-file-upload fa-3x text-primary mb-4"),
                        html.H3("Upload Your Resume", className="mb-3 text-light"),
                        html.P("Get AI-powered analysis of your resume", className="text-ghost-grey mb-4"),
                        dcc.Upload(
                            id='upload-resume',
                            children=html.Div([
                                html.A("Choose PDF File", className="btn btn-primary btn-lg px-5 py-3", style={'fontWeight': 'bold'})
                            ]),
                            style={'display': 'inline-block'},
                            multiple=False
                        ),
                        html.Small("Only PDF format supported • Maximum size: 5MB", className="d-block mt-3 text-ghost-grey")
                    ], className="text-center py-4")
                ]),
                dbc.CardFooter([
                    html.Div([
                        html.Small([
                            html.I(className="fas fa-shield-alt me-1"),
                            "Your data is processed locally and not stored."
                        ], className="text-ghost-grey")
                    ], className="text-center")
                ])
            ], className="analysis-card mb-5"),
            
            # Results Section
            html.Div(id="results-container"),
            
            # Footer
            html.Div([
                html.Hr(className="my-5"),
                html.Div([
                    html.P([
                        "💡 ",
                        "Extracting insights directly from your content",
                        " 💡"
                    ], className="text-center text-ghost-grey"),
                    html.P([
                        html.Small("🧠 AI-powered analysis  🔒 Privacy focused")
                    ], className="text-center text-ghost-grey mb-2"),
                ])
            ])
        ], width=12)
    ])
], fluid=True, className="px-4")


# Callback
@app.callback(
    Output('results-container', 'children'),
    Input('upload-resume', 'contents'),
    State('upload-resume', 'filename'),
    State('upload-resume', 'last_modified')
)
def process_resume(file_contents, filename, last_modified):
    if not file_contents:
        raise PreventUpdate
    
    try:
        # Check content type
        content_type, content_string = file_contents.split(',')
        
        # Validate file type
        if 'application/pdf' not in content_type:
            return dbc.Alert([
                html.H4("❌ Unsupported File Type", className="alert-heading text-light"),
                html.P("Please upload a PDF file.", className="text-light"),
                html.Hr(),
                html.P(f"Received: {content_type.split(';')[0]}", className="mb-0 text-light")
            ], color="danger", className="analysis-card")
        
        # Decode file
        decoded = base64.b64decode(content_string)
        
        # Check file size (5MB limit)
        if len(decoded) > 5 * 1024 * 1024:
            return dbc.Alert([
                html.H4("❌ File Too Large", className="alert-heading text-light"),
                html.P("Maximum file size is 5MB.", className="text-light"),
                html.Hr(),
                html.P(f"Uploaded: {len(decoded) / (1024*1024):.1f} MB", className="mb-0 text-light")
            ], color="danger", className="analysis-card")
        
        # Return loading state immediately
        loading = dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.Div([
                        dbc.Spinner(size="lg", color="primary")
                    ], className="spinner-container"),
                    html.H4("Analyzing Your Resume...", className="mb-3 text-light"),
                    html.P("AI is reading your resume and extracting insights", className="text-ghost-grey"),
                    dbc.Progress(value=100, striped=True, animated=True, className="mt-4 progress-gradient"),
                    html.Div([
                        html.Small(f"File: {filename}", className="text-muted"),
                        html.Br(),
                        html.Small(f"Type: {content_type.split(';')[0]}", className="text-muted")
                    ], className="mt-3")
                ], className="text-center py-5")
            ])
        ], className="analysis-card")
        
        # IMPORTANT: Return the loading state immediately
        # This allows the UI to show the loader while processing continues
        import threading
        from dash import callback_context
        import flask
        
        # Store the current callback context
        ctx = callback_context
        
        # Define a function to process in background
        def process_and_update():
            # Analyze resume directly from bytes
            results = analyze_resume_from_bytes(decoded)
            
            if "error" in results:
                error_result = dbc.Alert([
                    html.H4("❌ Analysis Error", className="alert-heading text-light"),
                    html.P(results["error"], className="text-light"),
                    html.Hr(),
                    html.P("Please ensure your resume is a valid PDF file.", className="mb-0 text-light")
                ], color="danger", className="analysis-card")
                
                # Update the output with error
                with app.server.app_context():
                    ctx.outputs_list[0]['value'] = error_result
            else:
                # Extract results
                text = results.get("text", "")
                contact_info = results.get("contact_info", {})
                analysis = results.get("analysis", {})
                stats = results.get("stats", {})
                
                # Create UI
                final_result = create_results_ui(text, contact_info, analysis, stats)
                
                # Update the output with final result
                with app.server.app_context():
                    ctx.outputs_list[0]['value'] = final_result
        
        # Start processing in background
        thread = threading.Thread(target=process_and_update)
        thread.daemon = True
        thread.start()
        
        # Return the loading state immediately
        return loading
        
    except Exception as e:
        print(f"Callback error: {e}")
        traceback.print_exc()
        return dbc.Alert([
            html.H4("Processing Error", className="alert-heading text-light"),
            html.P(f"Error: {str(e)}", className="text-light"),
        ], color="danger", className="analysis-card")

def create_results_ui(text, contact_info, analysis, stats):
    """Create the results UI"""
    
    overall = analysis.get("overall_assessment", {})
    score = overall.get("score", 50)
    grade = overall.get("grade", "C")
    summary = overall.get("summary", "")
    exp_level = overall.get("experience_level", "Not specified")
    
    # Score styling
    if score >= 80:
        score_class = "text-success"
        message = "Excellent!"
        icon = "fa-trophy"
    elif score >= 70:
        score_class = "text-primary"
        message = "Good!"
        icon = "fa-star"
    elif score >= 60:
        score_class = "text-warning"
        message = "Fair"
        icon = "fa-check-circle"
    else:
        score_class = "text-danger"
        message = "Needs Improvement"
        icon = "fa-exclamation-circle"
    
    # Extract data
    skills = analysis.get("extracted_skills", {})
    job_titles = analysis.get("suggested_job_titles", [])
    strengths = analysis.get("strengths_analysis", [])
    weaknesses = analysis.get("weaknesses_analysis", [])
    recommendations = analysis.get("recommendations", [])
    career_advice = analysis.get("career_advice", "")
    
    # Flatten skills for display
    all_skills = []
    for category in ["technical_skills", "soft_skills", "tools_platforms"]:
        if category in skills:
            all_skills.extend(skills[category])
    
    return dbc.Container([
        # Score and Overview Card
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        dbc.Row([
                            # Score Column
                            dbc.Col([
                                html.Div([
                                    html.Div([
                                        html.Span(f"{score}", className="score-display"),
                                        html.I(className=f"fas {icon} fa-2x ms-3 {score_class}")
                                    ], className="d-flex align-items-center justify-content-center mb-3"),
                                    html.H4(f"{message}", className=f"text-center {score_class}"),
                                    dbc.Progress(value=score, className="my-3", style={"height": "12px"}),
                                    html.Div([
                                        dbc.Badge(f"Grade: {grade}", color="primary", className="fs-6 px-3"),
                                        dbc.Badge(f"Level: {exp_level}", color="info", className="ms-2 fs-6 px-3"),
                                    ], className="text-center")
                                ])
                            ], width=4, className="border-end pe-4"),
                            
                            # Candidate Info
                            dbc.Col([
                                html.H5("👤 Candidate Profile", className="mb-4 text-light"),
                                html.Div([
                                    html.P([
                                        html.Strong("Name: ", className="text-light"),
                                        html.Span(contact_info.get("name", "Not detected"), className="text-light")
                                    ], className="mb-2"),
                                    html.P([
                                        html.Strong("Email: ", className="text-light"),
                                        html.Span(", ".join(contact_info.get("emails", ["Not provided"])), className="text-light")
                                    ], className="mb-2"),
                                    html.P([
                                        html.Strong("LinkedIn: ", className="text-light"),
                                        html.Span(contact_info.get("linkedin", ["Not provided"])[0] 
                                                    if contact_info.get("linkedin") else "Not provided", className="text-light")
                                    ], className="mb-2"),
                                    html.P([
                                        html.Strong("GitHub: ", className="text-light"),
                                        html.Span(contact_info.get("github", ["Not provided"])[0] 
                                                    if contact_info.get("github") else "Not provided", className="text-light")
                                    ], className="mb-2")
                                ]),
                                html.Hr(),
                                html.P([
                                    html.I(className="fas fa-info-circle me-2 text-info"),
                                    html.Span(summary, className="text-light")
                                ], className="small")
                            ], width=8)
                        ])
                    ])
                ], className="analysis-card mb-4")
            ], width=12)
        ]),
        
        # Skills and Job Titles
        dbc.Row([
            # Skills Column
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("🔧 Extracted Skills", className="mb-0 text-light"),
                        html.Small("AI-extracted from your resume", className="text-ghost-grey")
                    ]),
                    dbc.CardBody([
                        html.Div([
                            html.Div([
                                html.H6("Technical Skills", className="text-primary mb-3"),
                                html.Div([
                                    html.Span(skill, className="skill-badge")
                                    for skill in skills.get("technical_skills", [])[:15]
                                ]) if skills.get("technical_skills") else html.P("No technical skills detected", className="text-muted")
                            ], className="mb-4"),
                            
                            html.Div([
                                html.H6("Soft Skills", className="text-success mb-3"),
                                html.Div([
                                    html.Span(skill, className="skill-badge")
                                    for skill in skills.get("soft_skills", [])[:10]
                                ]) if skills.get("soft_skills") else html.P("No soft skills detected", className="text-muted")
                            ], className="mb-4"),
                            
                            html.Div([
                                html.H6("Tools & Platforms", className="text-info mb-3"),
                                html.Div([
                                    html.Span(skill, className="skill-badge")
                                    for skill in skills.get("tools_platforms", [])[:10]
                                ]) if skills.get("tools_platforms") else html.P("No tools detected", className="text-muted")
                            ])
                        ])
                    ]),
                    
                ], className="analysis-card")
            ], width=6),
            
            # Job Titles Column
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("🎯 Suggested Job Titles", className="mb-0 text-light"),
                        html.Small("Based on your resume content", className="text-ghost-grey")
                    ]),
                    dbc.CardBody([
                        html.Div([
                            dbc.Card([
                                dbc.CardBody([
                                    html.Div([
                                        html.H6(job.get("title", "Role"), className="mb-2 text-light"),
                                        html.Div([
                                            dbc.Progress(value=job.get("confidence", 0), className="mb-2"),
                                            html.Div([
                                                html.Small(f"{job.get('confidence', 0)}% match", className="text-light"),
                                                html.Small(f" • {job.get('reason', '')}", className="text-muted ms-2")
                                            ], className="d-flex justify-content-between")
                                        ])
                                    ])
                                ], className="job-title-card")
                            ], className="mb-3")
                            for job in job_titles[:3]
                        ]) if job_titles else html.P("No job titles suggested", className="text-muted")
                    ])
                ], className="analysis-card")
            ], width=6)
        ], className="mb-4"),
        
        # Detailed Analysis Tabs
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5("📊 Detailed Analysis", className="mb-0 text-light"),
                        html.Small(f"Source: {analysis.get('source', 'AI Analysis')}", className="text-ghost-grey")
                    ]),
                    dbc.CardBody([
                        dbc.Tabs([
                            # Strengths Tab
                            dbc.Tab([
                                html.Div([
                                    html.H6("✅ Your Key Strengths", className="mb-4 text-light"),
                                    html.Div([
                                        dbc.Card([
                                            dbc.CardBody([
                                                html.H6(strength.get("title", "Strength"), className="text-success"),
                                                html.P(strength.get("description", ""), className="text-light mb-2"),
                                                html.Div([
                                                    html.Small("Evidence: ", className="text-light"),
                                                    html.Span(strength.get("evidence", ""), className="text-muted")
                                                ], className="bg-light p-2 rounded small")
                                            ])
                                        ], className="mb-3")
                                        for strength in strengths[:3]
                                    ])
                                ], className="p-3")
                            ], label="Strengths"),
                            
                            # Weaknesses Tab
                            dbc.Tab([
                                html.Div([
                                    html.H6("📝 Areas for Improvement", className="mb-4 text-light"),
                                    html.Div([
                                        dbc.Card([
                                            dbc.CardBody([
                                                html.H6(weakness.get("title", "Area"), className="text-warning"),
                                                html.P(weakness.get("description", ""), className="text-light mb-2"),
                                                html.Div([
                                                    html.Small("Suggestion: ", className="text-light"),
                                                    html.Span(weakness.get("suggestion", ""), className="text-muted")
                                                ], className="bg-light p-2 rounded small")
                                            ])
                                        ], className="mb-3")
                                        for weakness in weaknesses[:3]
                                    ])
                                ], className="p-3")
                            ], label="Improvements"),
                            
                            # Recommendations Tab
                            dbc.Tab([
                                html.Div([
                                    html.H6("🚀 Action Plan", className="mb-4 text-light"),
                                    html.Div([
                                        dbc.ListGroup([
                                            dbc.ListGroupItem([
                                                html.Div([
                                                    dbc.Badge(
                                                        rec.get("priority", "Medium"),
                                                        color="danger" if rec.get("priority") == "High"
                                                        else "warning" if rec.get("priority") == "Medium"
                                                        else "secondary",
                                                        className="me-3"
                                                    ),
                                                    html.Div([
                                                        html.Strong(rec.get("action", ""), className="text-light"),
                                                        html.Small(f" ({rec.get('timeline', '')})", className="text-muted ms-2")
                                                    ])
                                                ], className="d-flex align-items-center")
                                            ])
                                            for rec in recommendations[:5]
                                        ], flush=True)
                                    ])
                                ], className="p-3")
                            ], label="Action Plan"),
                            
                            # Career Advice Tab
                            dbc.Tab([
                                html.Div([
                                    html.H6("💡 Career Advice", className="mb-4 text-light"),
                                    dbc.Card([
                                        dbc.CardBody([
                                            html.Div([
                                                html.I(className="fas fa-lightbulb fa-2x text-warning float-start me-3"),
                                                html.P(career_advice, className="lead text-light")
                                            ])
                                        ])
                                    ])
                                ], className="p-3")
                            ], label="Advice")
                        ])
                    ])
                ], className="analysis-card")
            ], width=12)
        ])
    ], fluid=True)


# Run Application
if __name__ == "__main__":
    print("\n")
    print(f"• Ollama Status: {'✅ Connected' if OLLAMA_AVAILABLE else '❌ Not available'}")
    if OLLAMA_AVAILABLE:
        print(f"• Model: {OLLAMA_MODEL}")
    print("• AI extracts everything from resume")
    print("• Dashboard: http://localhost:8050")
    print("\n📁 Ready to analyze resumes...\n")
    
    app.run(debug=False, port=8050, host='127.0.0.1')
