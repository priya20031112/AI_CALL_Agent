from flask import Flask, request, render_template, jsonify
from twilio.twiml.voice_response import VoiceResponse, Gather
from dotenv import load_dotenv
import os

# Import our custom systems
from knowledge_base import COURSE_INFO, FAQS
from question_answerer import detect_question_type, generate_answer
from sales_intelligence import (
    get_intro_message, get_interest_check, get_yes_response, get_no_response,
    get_answer_intro, get_after_answer, get_demo_message, get_close, handle_objection
)
from course_booking import (
    get_course_selection, get_course_confirmation, get_demo_booking,
    get_demo_time, get_booking_confirmation, get_closing,
    extract_course, extract_day, extract_time
)
from booking_system import create_booking

app = Flask(__name__)
load_dotenv()
print("=" * 70)
print("🔥 ADVANCED AI SALES AGENT WITH SMART BOOKING SYSTEM")
print("✅ Talks like experienced sales counselor")
print("✅ Course selection & slot booking automation")
print("=" * 70)

# =============================
# CALL STATE TRACKING
# =============================
call_state = {}
conversation_history = {}
turn_count = {}
student_interest = {}
student_phone = {}

def get_state(call_id):
    return call_state.get(call_id, {
        "stage": "intro",
        "questions_asked": 0,
        "demo_offered": False,
        "course_selected": None,
        "demo_date": None,
        "demo_time": None,
        "student_name": None,
        "student_mobile": None
    })

def update_state(call_id, state):
    call_state[call_id] = state


def is_affirmative(text):
    text_lower = text.lower()
    return any(word in text_lower for word in ["yes", "ya", "yup", "sure", "okay", "of course", "absolutely", "want", "i do", "నేను", "అవును", "సరే"])


def is_negative(text):
    text_lower = text.lower()
    return any(word in text_lower for word in ["no", "don't", "dont", "nah", "not interested", "కాదు", "లేదు"])


def add_to_history(call_id, role, text):
    if call_id not in conversation_history:
        conversation_history[call_id] = []
    conversation_history[call_id].append({"role": role, "text": text})


def get_turn(call_id):
    return turn_count.get(call_id, 0)


def increment_turn(call_id):
    turn_count[call_id] = get_turn(call_id) + 1


def get_stage_followup_prompt(state):
    stage = state.get("stage", "intro")
    if stage == "intro":
        return get_interest_check()
    elif stage == "course_selection":
        return get_course_selection()
    elif stage == "demo_interest":
        return get_demo_booking(state.get("course_selected"))
    elif stage == "demo_date_selection":
        return get_demo_booking(state.get("course_selected"))
    elif stage == "demo_time_selection":
        return get_demo_time()
    elif stage == "collect_student_details":
        if state.get("student_name") is None:
            return "నీ పేరు చెప్పు బ్రో, please."
        elif state.get("student_mobile") is None:
            return "నీ mobile number ఇవ్వండి బ్రో."
        else:
            return "ఇది correct కాదా బ్రో? yes or no చెప్పు బ్రో."
    return get_after_answer()


def try_general_question_response(response, call_id, user_input, state):
    question_type, direct_answer = detect_question_type(user_input)
    if question_type == "unclear":
        return False

    if direct_answer:
        ai_response = direct_answer
    else:
        ai_response = generate_answer(question_type, user_input)

    if question_type not in ["who_are_you", "what_can_you_do"]:
        ai_response = get_answer_intro(question_type) + " " + ai_response

    response.say(ai_response, voice="Polly.Aditi", language="en-IN")
    add_to_history(call_id, "Agent", ai_response)

    follow_up = get_stage_followup_prompt(state)
    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )
    gather.say(follow_up, voice="Polly.Aditi", language="en-IN")
    response.append(gather)
    return True

# =============================
# HEALTH CHECK
# =============================
@app.route("/", methods=["GET"])
def health():
    return "✅ Real AI Sales Agent is running with ACTUAL course knowledge!"


# =============================
# SIMPLE WEB DASHBOARD
# =============================
@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("index.html")


@app.route("/trigger_call", methods=["POST"])
def trigger_call():
    """Trigger an outbound call via Twilio (uses same env vars as call.py).
    Expects JSON: { "phone": "+123..." }
    """
    from twilio.rest import Client
    phone = request.json.get("phone") if request.is_json else request.form.get("phone")
    if not phone:
        return jsonify({"error": "Phone number required"}), 400

    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    VOICE_WEBHOOK_URL = os.getenv("VOICE_WEBHOOK_URL", "").strip()
    SIMULATE_MODE = os.getenv("SIMULATE_MODE", "").strip().lower() in ("1", "true", "yes")

    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, VOICE_WEBHOOK_URL]):
        return jsonify({"error": "Missing Twilio configuration in environment"}), 500

    if SIMULATE_MODE or os.getenv("SIMULATE_MODE", "").lower() in ("1", "true", "yes"):
        # Simulate invocation of the webhook similar to call.py
        import urllib.parse, urllib.request
        form_data = urllib.parse.urlencode({
            "CallSid": "SIMULATED_CALL_SID",
            "From": phone,
            "To": TWILIO_FROM_NUMBER,
            "CallStatus": "in-progress",
        }).encode("utf-8")
        req = urllib.request.Request(VOICE_WEBHOOK_URL, data=form_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode("utf-8")
            return jsonify({"status": "simulated", "webhook_response": body})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # Real call via Twilio
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        call = client.calls.create(to=phone, from_=TWILIO_FROM_NUMBER, url=VOICE_WEBHOOK_URL)
        return jsonify({"status": "started", "call_sid": call.sid})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

# =============================
# INITIAL VOICE CALL ENDPOINT
# =============================
@app.route("/voice", methods=["POST"])
def voice():
    """
    When student receives the call, this is what they hear first
    """
    call_id = request.form.get("CallSid", "default")
    phone = request.form.get("From", "unknown")
    
    # Store student phone number for booking
    student_phone[call_id] = phone
    
    call_state[call_id] = {
        "stage": "intro",
        "questions_asked": 0,
        "demo_offered": False,
        "course_selected": None,
        "demo_date": None,
        "demo_time": None,
        "student_name": None,
        "student_mobile": None
    }
    
    response = VoiceResponse()
    
    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )
    
    opening = get_intro_message()
    interest_q = get_interest_check()
    full_message = opening + " " + interest_q
    
    gather.say(full_message, voice="Polly.Aditi", language="en-IN")
    response.append(gather)
    
    return str(response)

# =============================
# MAIN PROCESSING ENDPOINT
# =============================
@app.route("/process", methods=["POST"])
def process():
    """
    MAIN ENGINE: Listens to student, detects question, gives REAL answer
    """
    user_input = request.form.get("SpeechResult", "").strip()
    call_id = request.form.get("CallSid", "default")
    
    response = VoiceResponse()
    state = get_state(call_id)
    current_turn = get_turn(call_id)

    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )
    
    # =============================
    # HANDLE NO SPEECH
    # =============================
    if not user_input:
        response.say(
            "Sorry, I could not hear you clearly. Please repeat. Ask about course, fees, placements, or anything else.",
            voice="Polly.Aditi",
            language="en-IN"
        )
        response.append(gather)
        return str(response)
    
    # =============================
    # HANDLE HARD EXIT
    # =============================
    if any(word in user_input.lower() for word in ["stop calling", "don't call", "remove me", "not interested at all"]):
        response.say("Okay, no problem! All the best!", voice="Polly.Aditi", language="en-IN")
        response.hangup()
        return str(response)
    
    # =============================
    # TRACK THE CONVERSATION
    # =============================
    add_to_history(call_id, "Student", user_input)
    increment_turn(call_id)
    current_turn = get_turn(call_id)
    
    print(f"\n[Turn {current_turn}] Student: {user_input}")
    
    # =============================
    # INITIAL STAGE: YES/NO TO BECOME SOFTWARE ENGINEER
    # =============================
    if state["stage"] == "intro":
        if is_affirmative(user_input):
            ai_response = get_yes_response()
            state["stage"] = "course_selection"
            update_state(call_id, state)
        elif is_negative(user_input):
            closing_msg = get_no_response()
            response.say(closing_msg, voice="Polly.Aditi", language="en-IN")
            response.hangup()
            return str(response)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_interest_check() + " దయచేసి yes లేదా no చెప్పండి బ్రో."
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)
    
    # =============================
    # STAGE: COURSE SELECTION
    # =============================
    elif state["stage"] == "course_selection":
        course = extract_course(user_input)
        if course:
            ai_response = get_course_confirmation(course)
            state["course_selected"] = course
            state["stage"] = "demo_interest"
            update_state(call_id, state)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_course_selection()
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)
    
    # =============================
    # STAGE: DEMO INTEREST
    # =============================
    elif state["stage"] == "demo_interest":
        course_name = state.get("course_selected")
        if is_affirmative(user_input):
            ai_response = get_demo_booking(course_name)
            state["stage"] = "demo_date_selection"
            update_state(call_id, state)
        elif is_negative(user_input):
            ai_response = "సరే బ్రో, ఏ problem లేదు బ్రో. డిమో ఇంకా పిక్క్కు చేయాలని కంటే తర్వాత contact చేయవచ్చు బ్రో. Thanks బ్రో!"
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.hangup()
            return str(response)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_demo_booking(course_name)
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)
    
    # =============================
    # STAGE: DEMO DATE SELECTION
    # =============================
    elif state["stage"] == "demo_date_selection":
        demo_day = extract_day(user_input)
        if demo_day:
            ai_response = get_demo_time()
            state["demo_date"] = demo_day
            state["stage"] = "demo_time_selection"
            update_state(call_id, state)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            course_name = state["course_selected"]
            ai_response = get_demo_booking(course_name)
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)
    
    # =============================
    # STAGE: DEMO TIME SELECTION
    # =============================
    elif state["stage"] == "demo_time_selection":
        demo_time = extract_time(user_input)
        if demo_time:
            ai_response = "బాగుంది బ్రో! నీకు {demo_time} time convenient బ్రో. ఇప్పుడు నీ details collect చేస్తాను బ్రో. మొదట నీ పేరు చెప్పు బ్రో?".format(demo_time=demo_time)
            state["demo_time"] = demo_time
            state["stage"] = "collect_student_details"
            update_state(call_id, state)
        else:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            ai_response = get_demo_time()
            response.say(ai_response, voice="Polly.Aditi", language="en-IN")
            response.append(gather)
            return str(response)
    
    # =============================
    # STAGE: COLLECT STUDENT DETAILS
    # =============================
    elif state["stage"] == "collect_student_details":
        if state["student_name"] is None:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            # First time - asking for name
            state["student_name"] = user_input.strip()
            ai_response = "ధన్యవాదాలు {name} బ్రో! ఇప్పుడు నీ mobile number చెప్పు బ్రో?".format(name=state["student_name"])
            update_state(call_id, state)
        elif state["student_mobile"] is None:
            if try_general_question_response(response, call_id, user_input, state):
                return str(response)
            # Got name, now asking for mobile
            state["student_mobile"] = user_input.strip()
            course_name = state["course_selected"]
            from booking_system import get_course_info
            course_info = get_course_info(course_name)
            course_display = course_info["name"] if course_info else course_name
            ai_response = "సరే {name} బ్రో! నీ mobile number {mobile} ని confirm చేస్తున్నాను 브ோ. నీ course: {course} బ్రో. ఇది correct ఆ బ్రో? Yes or No బ్రో?".format(
                name=state["student_name"], 
                mobile=state["student_mobile"],
                course=course_display
            )
            update_state(call_id, state)
        else:
            # Confirming course selection
            if is_affirmative(user_input):
                # Create booking with all details
                course_name = state["course_selected"]
                from booking_system import get_course_info
                course_info = get_course_info(course_name)
                
                booking = create_booking(
                    phone_number=state["student_mobile"],
                    course_name=course_info["name"] if course_info else "Unknown",
                    demo_date=state["demo_date"],
                    demo_time=state["demo_time"],
                    student_name=state["student_name"]
                )
                
                ai_response = "పర్ఫెక్ట్ బ్రో! {name}, నీ booking confirmed బ్రో! Course: {course} బ్రో, Date: {date} బ్రో, Time: {time} బ్రో. ఈ details నీ mobile కి message లో కూడా పంపిస్తాం బ్రో.".format(
                    name=state["student_name"],
                    course=course_info["name"] if course_info else course_name,
                    date=state["demo_date"],
                    time=state["demo_time"]
                )
                state["stage"] = "booking_complete"
                update_state(call_id, state)
            elif is_negative(user_input):
                ai_response = get_course_selection()
                state["stage"] = "course_selection"
                update_state(call_id, state)
            else:
                if try_general_question_response(response, call_id, user_input, state):
                    return str(response)
                ai_response = "సరే బ్రో, ఈ డీటెయిల్స్ confirm కావాలా? Yes లేదా No చెప్పు బ్రో."
        
        response.say(ai_response, voice="Polly.Aditi", language="en-IN")
        response.append(gather)
        return str(response)
    
    # =============================
    # STAGE: BOOKING COMPLETE
    # =============================
    elif state["stage"] == "booking_complete":
        course_name = state["course_selected"]
        from booking_system import get_course_info, get_student_booking
        course_info = get_course_info(course_name)
        booking = get_student_booking(student_phone.get(call_id, "unknown"))
        
        closing_msg = get_closing(booking) if booking else "Thank you!"
        response.say(closing_msg, voice="Polly.Aditi", language="en-IN")
        response.hangup()
        return str(response)
    
    # =============================
    # STAGE: ACTIVE (QUESTIONS)
    # =============================
    else:
        # DETECT QUESTION TYPE & GET ANSWER - MID FLOW
        question_type, direct_answer = detect_question_type(user_input)
        
        if direct_answer:
            # Add introduction to answer like experienced sales person
            intro = get_answer_intro(question_type)
            actual_answer = generate_answer(question_type, user_input)
            ai_response = intro + " " + actual_answer
            print(f"[Answer Type] {question_type}")
        elif question_type == "general_doubt":
            # Handle general doubts
            ai_response = generate_answer(question_type, user_input)
            print(f"[Doubt Detected] General doubt clarification")
        else:
            ai_response = (
                "నీ question నాకు clear కాలేదు బ్రో. "
                "దయచేసి course content, fees, placement, projects, internship, లేదా schedule గురించి అడగండి బ్రో. "
                "నేను honest answer ఇస్తాను బ్రో."
            )

    # =============================
    # SPEAK THE RESPONSE
    # =============================
    response.say(ai_response, voice="Polly.Aditi", language="en-IN")
    add_to_history(call_id, "Agent", ai_response)
    
    # =============================
    # DECIDE NEXT STEP - INTELLIGENT FOLLOW UP
    # =============================
    gather = Gather(
        input="speech",
        action="/process",
        method="POST",
        timeout=10,
        speechTimeout="auto",
        language="en-IN"
    )
    
    # Use smart continuation from sales intelligence
    demo_msg = get_demo_message(current_turn)
    
    if demo_msg and not state["demo_offered"]:
        # Time to push demo
        follow_up = demo_msg
        state["demo_offered"] = True
        update_state(call_id, state)
    elif current_turn >= 8:
        # If too many turns, prepare to close call
        follow_up = get_after_answer()
    else:
        # Normal continuation - ask for more questions
        follow_up = get_after_answer()
    
    gather.say(follow_up, voice="Polly.Aditi", language="en-IN")
    response.append(gather)
    
    print(f"[Follow-up] {follow_up}\n")
    
    return str(response)

# =============================
# RUN THE APP
# =============================
if __name__ == "__main__":
    print("\n🚀 Starting ADVANCED AI Sales Agent (10+ Years Experience)...")
    print("📱 Webhook endpoint: POST /voice")
    print("✅ Talks like experienced institute sales counselor")
    print("✅ Human-like responses with intelligence")
    print("✅ Uses real knowledge base for answers\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
