"""R K LITTLE BUDS (E.M) High School - school records system.
Run:  pip install -r requirements.txt  &&  python app.py   ->  http://127.0.0.1:5000
Default PINs: admin123 (Admin) and staff123 (Staff) - change both after first login
"""
from urllib.parse import quote
import csv, hashlib, io, json, math, os, re, secrets, shutil, sqlite3, time, uuid
from collections import Counter
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "school.db")
SCHOOL = "R K LITTLE BUDS (E.M) High School"
CLASSES = ["Nursery", "LKG", "UKG"] + [str(i) for i in range(1, 11)]
PALETTE = ["#0b4ea2", "#f26522", "#1a8a3a", "#ffb300", "#1b8a8a", "#7b2d8e", "#e31e24"]

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # upload limit per request (photos + videos)
LOGO = os.path.join(BASE, "static", "logo.png")
UPLOADS = os.path.join(BASE, "static", "uploads")
IMG_EXT = {"png", "jpg", "jpeg", "webp"}
VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "ogg"}


@app.errorhandler(413)
def too_large(_):
    flash("That upload is too large (limit: 300 MB at a time). Please upload fewer or smaller files at once.")
    return redirect(request.referrer or url_for("home"))

# (key, label, type, options)  -> type: text | number | date | tel | select
MODULES = {
    "students": {"title": "Students", "icon": "🎓", "fields": [
        ("name", "Student name", "text"), ("cls", "Class", "select", CLASSES),
        ("roll", "Roll no.", "text"), ("dob", "Date of birth", "date"),
        ("gender", "Gender", "select", ["Male", "Female"]),
        ("parent", "Parent / Guardian", "text"), ("phone", "Mobile number", "tel"),
        ("addr", "Address", "text"), ("photo", "Photo", "photo"),
        ("section", "Section", "select", ["", "A", "B", "C", "D", "E", "F"])],
        "cols": ["name", "cls", "section", "roll", "parent", "phone"]},
    "teachers": {"title": "Teachers", "icon": "👩‍🏫", "fields": [
        ("name", "Teacher name", "text"), ("subject", "Subject", "text"),
        ("qual", "Qualification", "text"), ("classes", "Classes taught (e.g. LKG, UKG, 1-5)", "text"),
        ("phone", "Phone", "tel"), ("doj", "Date of joining", "date"), ("salary", "Monthly salary (₹)", "number"),
        ("photo", "Photo (shown on website)", "photo"), ("show", "Show on website", "select", ["Yes", "No"])],
        "cols": ["name", "subject", "classes", "qual", "phone", "salary"]},
    "fees": {"title": "Fees", "icon": "💰", "fields": [
        ("student", "Student name", "text"), ("cls", "Class", "select", CLASSES),
        ("term", "Term", "select", ["Term 1", "Term 2", "Term 3", "Annual"]),
        ("due", "Amount due (₹)", "number"), ("paid", "Amount paid (₹)", "number"),
        ("date", "Payment date", "date"),
        ("mode", "Mode", "select", ["Cash", "UPI", "Cheque", "Bank transfer"])],
        "cols": ["student", "cls", "term", "due", "paid", "bal", "date", "mode"]},
    "admissions": {"title": "Admissions", "icon": "📝", "fields": [
        ("name", "Applicant name", "text"), ("cls", "Applying for class", "select", CLASSES),
        ("parent", "Parent / Guardian", "text"), ("phone", "Phone", "tel"),
        ("date", "Application date", "date"),
        ("status", "Status", "select", ["Applied", "Interview", "Admitted", "Rejected"]),
        ("source", "How did they hear of us?", "select", ["Website", "Phone", "Walk-in", "Referral", "Flyer / Banner", "Other"]),
        ("note", "Follow-up note", "text"), ("callback", "Call back on", "optdate")],
        "cols": ["name", "cls", "parent", "phone", "date", "status", "callback"]},
    "exams": {"title": "Exams & Marks", "icon": "📑", "group": "progress", "fields": [
        ("sid", "Student", "student"),
        ("exam", "Exam", "select", ["Weekly Test", "Unit Test 1", "Unit Test 2", "Quarterly", "Half-Yearly", "Pre-Final", "Annual", "Other"]),
        ("subject", "Subject", "text"), ("date", "Exam date", "date"), ("max", "Maximum marks", "number"),
        ("marks", "Marks obtained", "number"), ("attended", "Attendance at exam", "select", ["Attended", "Absent"]),
        ("remarks", "Remarks", "text")],
        "cols": ["sid", "exam", "subject", "date", "marks", "max", "attended"]},
    "activities": {"title": "Activities", "icon": "🏅", "group": "progress", "fields": [
        ("sid", "Student", "student"),
        ("kind", "Type", "select", ["Sports", "Dance", "Music", "Art & Craft", "Yoga", "Science", "Quiz / Competition", "Cultural", "Other"]),
        ("title", "Activity / event name", "text"), ("date", "Date", "date"),
        ("award", "Position / award", "text"), ("remarks", "Remarks", "text")],
        "cols": ["sid", "kind", "title", "date", "award"]},
    "competitive": {"title": "Competitive Exams", "icon": "🏆", "group": "progress", "fields": [
        ("sid", "Student", "student"),
        ("exam", "Exam", "select", ["Navodaya", "IIT Foundation", "Olympiad", "NTSE", "Scholarship", "Other"]),
        ("date", "Exam date", "date"),
        ("status", "Status", "select", ["Registered", "Attended", "Result awaited", "Qualified", "Not qualified"]),
        ("score", "Score / rank", "text"), ("remarks", "Remarks", "text")],
        "cols": ["sid", "exam", "date", "status", "score"]},
    "remarks": {"title": "Teacher Remarks", "icon": "💬", "group": "progress", "fields": [
        ("sid", "Student", "student"), ("date", "Date", "date"),
        ("kind", "Type", "select", ["Academic", "Behaviour", "Strength", "Needs improvement", "General"]),
        ("remark", "Remark", "text"), ("by", "By (teacher)", "text")],
        "cols": ["sid", "date", "kind", "remark", "by"]},
    "attendance": {"title": "Attendance", "icon": "🗓️", "group": "progress", "fields": [
        ("sid", "Student", "student"), ("month", "Month", "month"),
        ("working", "Working days", "number"), ("present", "Days present", "number")],
        "cols": ["sid", "month", "working", "present", "attpct"]},
    "notices": {"title": "Notices & Homework", "icon": "📌", "group": "comm", "fields": [
        ("title", "Title", "text"),
        ("kind", "Type", "select", ["Circular", "Holiday", "Exam timetable", "Homework", "Event", "Other"]),
        ("audience", "For class", "select", ["All classes"] + CLASSES), ("date", "Date", "date"),
        ("details", "Details", "textarea")],
        "cols": ["title", "kind", "audience", "date", "reads"]},
    "feedback": {"title": "Parent Feedback", "icon": "✉️", "group": "comm", "fields": [
        ("sid", "Student", "student"), ("date", "Date", "date"), ("message", "Message", "textarea"),
        ("status", "Status", "select", ["New", "Seen", "Replied"])],
        "cols": ["sid", "date", "message", "status"]},
}
LABELS = {"name": "Name", "cls": "Class", "roll": "Roll", "parent": "Parent", "phone": "Phone",
          "subject": "Subject", "qual": "Qualification", "salary": "Salary", "student": "Student",
          "term": "Term", "due": "Due", "paid": "Paid", "bal": "Balance", "date": "Date",
          "mode": "Mode", "status": "Status", "classes": "Classes", "sid": "Student", "exam": "Exam", "marks": "Marks", "max": "Max",
          "attended": "At exam", "kind": "Type", "title": "Activity", "award": "Award / position", "score": "Score / rank",
          "remark": "Remark", "by": "By", "month": "Month", "working": "Working days", "present": "Present", "attpct": "Attendance %", "section": "Section", "reads": "Read by", "audience": "For class", "message": "Message", "note": "Follow-up", "callback": "Call back on", "details": "Details"}


# ---------- public website content (edit freely) ----------
DEFAULT_SITE = {
    "motto": "Nurture. Educate. Inspire.",
    "quote": "Little buds today, shining leaders tomorrow.",  # shown under the school name on the home page
    "tagline": "English Medium High School · Where every little bud blossoms",
    "about": [
        "R K Little Buds (E.M) High School is a caring English Medium school offering quality education from pre-primary to high school. We combine a well-planned academic programme with sports, arts and life-skill activities so that every child grows in knowledge, character and confidence.",
        "Our teachers give personal attention to every student, and our campus is safe, clean and joyful - a second home where little buds blossom.",
    ],
    "highlights": [("LKG - 10", "Classes offered"), ("English", "Medium of instruction"),
                   ("Caring", "Safe, friendly campus"), ("All-round", "Studies + activities")],
    "vision": ["Shape confident, responsible citizens", "Spark interest in science and technology", "Build life skills for a bright future"],
    "mission": ["All-round growth through studies and co-curricular activities", "Care for the environment",
                "Encourage social responsibility", "Learn together and support each other"],
    # (icon, tab title, short text, bullet points)
    "activities": [
        ("⚽", "Sports & Games", "Healthy bodies, team spirit and fair play.", ["Athletics and annual sports day", "Kho-kho, kabaddi, cricket, football", "Indoor games and chess", "Inter-house competitions"]),
        ("💃", "Dance & Cultural", "Stage confidence through traditional and modern dance.", ["Classical and folk dance", "Annual day performances", "Fancy dress and skits", "Cultural festivals"]),
        ("🎵", "Music", "Singing and instruments for every young voice.", ["Group singing and devotional songs", "Keyboard and percussion basics", "Music competitions", "Morning assembly performances"]),
        ("🎨", "Art & Craft", "Colours, clay and creativity every week.", ["Drawing and painting", "Clay modelling and paper craft", "Best-out-of-waste projects", "Art exhibitions"]),
        ("🔬", "Science & Maths Club", "Learning by doing, experimenting and exploring.", ["Hands-on science experiments", "Science exhibition", "Maths puzzles and Olympiad practice", "Working models"]),
        ("🧘", "Yoga & Health", "Calm minds and fit bodies.", ["Daily yoga and breathing exercises", "Health and hygiene awareness", "Meditation sessions", "Health check-up camps"]),
        ("🌳", "Eco / Nature Club", "Little buds who care for the planet.", ["Tree planting and school garden", "Plastic-free campus drives", "Nature walks", "Environment day programmes"]),
        ("📖", "Library & Reading", "Building a love for books.", ["Weekly library period", "Story-telling sessions", "Book-review and reading challenges", "Spelling bee and recitation"]),
        ("💻", "Computer & Coding", "Early digital skills for tomorrow.", ["Computer lab practice", "Typing and basic coding", "Safe internet habits", "Digital drawing"]),
        ("🏆", "Competitions & Quiz", "Platforms to shine and win.", ["Quiz and elocution", "Drawing and handwriting contests", "Inter-school events", "Prize distribution"]),
        ("🎉", "Celebrations & Events", "Festivals and days that bring us together.", ["Independence and Republic Day", "Teachers' Day and Children's Day", "Pongal / Diwali / Christmas celebrations", "Annual Day"]),
    ],
    "admission_steps": [
        ("Enquiry", "Visit the school office or fill the enquiry form below."),
        ("Application", "Collect and submit the filled application form."),
        ("Interaction", "A short, friendly interaction with the child and parents."),
        ("Documents", "Submit the required documents for verification."),
        ("Confirmation", "Pay the fees and receive your admission confirmation."),
    ],
    "documents": ["Birth certificate (copy)", "Transfer certificate (for Class 2 and above)", "Previous year report card / marks sheet",
                  "Aadhaar card copy of child and parents", "Passport size photos of the child", "Address proof"],
    # EDIT these to match your school's real rules
    "age_rules": [("LKG", "3 years +"), ("UKG", "4 years +"), ("Class 1", "5 years +"),
                  ("Class 2 - 10", "Transfer certificate and previous report card")],
    "address": "Add school address here", "phone": "Add phone number here",
    "email": "Add email here", "hours": "Mon - Sat, 9:00 AM - 4:00 PM",
    "facilities": [("🏫", "Airy Classrooms", "Bright, well-ventilated rooms."), ("🔬", "Science Lab", "Hands-on experiments."),
                   ("💻", "Computer Lab", "Early digital skills."), ("📖", "Library", "Books to build a reading habit."),
                   ("🚌", "Transport", "Safe school buses."), ("🛝", "Play Area", "Open space for play.")],
    "gallery": [("🎓 Annual Day", "#0b4ea2", "#4a7fd6"), ("🏅 Sports Day", "#f26522", "#ffb300"),
                ("🔬 Science Fair", "#7b2d8e", "#b46bc9"), ("🎨 Art Class", "#1b8a8a", "#5ec4c4"),
                ("🎉 Celebrations", "#d6247d", "#f27fb0"), ("🌳 Nature Club", "#1a8a3a", "#6cc57f")],
    "photos": [],
    "events": [],
    # Messages shown in "About School". Edit them in Admin > About & Leadership.
    "about_people": [
        {"id": "mgmt", "role": "Management", "name": "Chairman & Management", "icon": "🏛️", "photo": "",
         "message": "Welcome to R K Little Buds (E.M) High School. Our management is committed to giving every child a strong foundation in education, values and discipline. We invest in a safe campus, dedicated teachers and good learning facilities so that our students grow into confident, responsible citizens. We thank all parents for their trust and support."},
        {"id": "principal", "role": "Principal", "name": "Principal's name", "icon": "🎓", "photo": "",
         "message": "Education at our school is a joyful journey. We nurture curiosity, encourage questions and celebrate every small success. Through caring guidance and a balance of academics, sports and arts, we help each child discover their strengths. Together with parents and teachers, we are building the leaders of tomorrow."},
        {"id": "hm", "role": "Head Master", "name": "Head Master's name", "icon": "📘", "photo": "",
         "message": "Our focus is on discipline, regular learning and personal attention to every student. We follow a well-planned academic calendar, watch each child's progress closely and support them to do their best. We welcome parents to stay in touch with us about their child's growth."},
        {"id": "teachers", "role": "Teachers", "name": "Our Teaching Team", "icon": "👩‍🏫", "photo": "",
         "message": "Our teachers are the heart of our school. They teach with patience and love, make lessons interesting and encourage every child to try, learn and shine. We treat every student as our own child and work hand in hand with parents to bring out the best in them."},
    ],
}
# Everything above is only the DEFAULT. After you save in Admin Panel > Edit Website, your changes are stored in the database.


# ---------- content taken from the school's flyers and banner (edit in Admin > Edit Website) ----------
DEFAULT_SITE.update({
    "telugu_motto": [["విద్య", "Education"], ["విజ్ఞానం", "Knowledge"], ["వికాసం", "Growth"]],
    "recognised": "Recognised by Govt. of A.P.",
    "range_te": "నర్సరీ నుండి 10వ తరగతి వరకు", "range_en": "Nursery to 10th Class",
    "quote": "నిర్ణయం మీది... బాధ్యత మాది...", "quote_en": "The decision is yours... the responsibility is ours.",
    "badges": [["Admissions are in Progress", ""],
               ["IIT foundation from Class 6", "6వ తరగతి నుండి IIT విద్యాబోధన"],
               ["Navodaya classes with Class 4 & 5", "4, 5 తరగతులతో పాటుగా నవోదయ క్లాసులు నిర్వహించబడును"]],
    "highlights": [["Nursery - 10", "Classes offered"], ["Govt. of A.P.", "Recognised school"],
                   ["100%", "SSC pass result"], ["IIT & Navodaya", "Foundation classes"]],
    "about": [
        "R.K. Little Buds E.M. School, Chitrada-Pavara, is recognised by the Government of Andhra Pradesh and offers English-medium education from Nursery to 10th class. It is run by founders who are themselves experienced and dedicated teachers, which makes our school unique in the area.",
        "With good discipline and the best results, we have earned the trust of parents in Chitrada and the nearby villages. With new, up-to-date teaching plans, we give education that stands on par with the corporate schools.",
    ],
    "about_te": [
        "విద్యారంగంలో సుదీర్ఘ అనుభవం, అంకిత భావం గల వ్యవస్థాపకులే అధ్యాపకులుగా నడుపబడుచున్న ఏకైక విద్యాసంస్థ.",
        "ఉత్తమ క్రమశిక్షణతో అత్యుత్తమ ఫలితాలను అందిస్తూ, చిత్రాడ మరియు పరిసర ప్రాంత తల్లిదండ్రుల మన్ననలను పొంది, నేటి కాలానికి అనుగుణంగా సరిక్రొత్త విద్యా ప్రణాళికలతో “కార్పొరేటు” సంస్థలకు ధీటుగా విద్యను అందిస్తున్న ఏకైక విద్యాసంస్థ – ఆర్.కె. లిటిల్ బడ్స్",
    ],
    "specialities": [
        ["అర్హత, అనుభవం, అంకిత భావం గల ఉపాధ్యాయులచే విద్యాబోధన", "Teaching by qualified, experienced and dedicated teachers"],
        ["ఒత్తిడిలేని విద్యకు ప్రాధాన్యత", "Priority to stress-free education"],
        ["పిల్లల ప్రగతిని నేరుగా తల్లిదండ్రులకు తెలియచేయుట", "Children's progress is told directly to the parents"],
        ["తరగతి గదిలో పరిమిత సంఖ్యలో విద్యార్థులు", "A limited number of students in each classroom"],
        ["జ్ఞాపకశక్తిని పెంపొందించే మెమొరి టెక్నిక్స్ నేర్పుట", "Memory techniques taught to improve memory power"],
        ["1వ తరగతి నుండి కంప్యూటర్ బోధన", "Computer teaching from Class 1"],
        ["ఇంగ్లీష్ మాట్లాడే విధంగా కమ్యూనికేషన్ స్కిల్స్ (L.S.R.W) నేర్పుట", "Communication skills (L.S.R.W) taught so that students can speak English"],
        ["పిల్లల మానసిక, శారీరక ఎదుగుదలకు యోగ, మెడిటేషన్ మరియు డాన్స్ క్లాసులు నిర్వహించుట", "Yoga, meditation and dance classes for the mental and physical growth of children"],
        ["షార్ట్‌కట్ పద్ధతిలో మేథ్స్‌లో విద్యాబోధన", "Maths taught with shortcut methods"],
        ["ప్రతి వారాంతరంలో జరిగిన తరగతులపై పరీక్షలు నిర్వహించుట, ఆ ఫలితాలను తల్లిదండ్రులకు తెలుపుట", "Weekly tests on the classes taken, with the results shared with parents"],
        ["ప్రథమ మరియు మాధ్యమిక వంటి హిందీ పరీక్షలు వ్రాయించబడును", "Hindi exams such as Prathama and Madhyama are written"],
        ["విద్యార్థులు కష్టంగా భావించే ఇంగ్లీష్ భాషను సులభమైన రీతిలో బోధించడం, విద్యార్థులలో భాషపట్ల ప్రేమాభిమానాలు కల్గించే ఉత్తమ రీతిలో విద్యను అందించడం", "English, which students find difficult, is taught in an easy way that builds love for the language"],
        ["వెనుకబడిన విద్యార్థినీ, విద్యార్థులపై ప్రత్యేక శ్రద్ధ", "Special attention to students who are lagging behind"],
        ["విద్యార్థులకు ఎల్‌సిడి ప్రొజెక్టర్ ద్వారా విద్యాబోధన", "Teaching through an LCD projector"],
        ["6వ తరగతి నుండి IIT విద్యాబోధన", "IIT foundation teaching from Class 6"],
        ["4, 5 తరగతులతో పాటుగా నవోదయ క్లాసులు నిర్వహించబడును", "Navodaya classes along with Class 4 and 5"],
    ],
    "success_te": "విజయం మీది... ఆ విజయాన్ని అందించే బాధ్యత మాది...",
    "success_en": "The success is yours... the responsibility of delivering it is ours.",
    "results": {"total": 16, "passed": 16, "a500": 10, "a400": 5, "b400": 1,
                "caption": "Congratulations to all our students on this result!"},
    "campus_te": "యూనివర్శిటీ స్థాయిలో విద్యా ప్రాంగణం", "campus_en": "A university-level learning campus",
    "campus1_cap": "R.K. Little Buds Campus", "campus2_cap": "R.K. Little Buds E.M. High School",
    "bus_te": "వాహన సదుపాయం కలదు", "bus_en": "Transport facility available",
    "bus_text": "Our school bus is available for students.",
    "images": {"campus1": "img/campus.jpg", "campus2": "img/building.jpg", "results": "img/results.jpg", "bus": "img/bus.png", "hero": "img/hero-building.jpg"},
    "collage": ["img/life1.png", "img/life2.png", "img/life3.png", "img/life4.png", "img/life5.png", "img/life6.png"],
    "campuses": [
        ["Chitrada-Pavara campus (E.M. High School)",
         "NH-216, Pithapuram-Kakinada Road, Near Mahalakshmi Temple, Chitrada-Pavara, Samarlakota Mandal, Kakinada District",
         "NH-216, పిఠాపురం-కాకినాడ రోడ్, మహాలక్ష్మి ఆలయం దగ్గర, చిత్రాడ-పవర, సామర్లకోట మండలం, కాకినాడ జిల్లా",
         "85199 77744, 92901 11182"],
    ],
    "address": "Near Mahalakshmi Temple, Main Road, Chitrada, Pavara",
    "phone": "85199 77744, 92901 11182", "email": "", "hours": "",
    "age_rules": [["Nursery to Class 10", "Admissions are in progress"], ["Class 4 & 5", "Navodaya classes along with the regular classes"],
                  ["Class 6 onwards", "IIT foundation teaching"], ["Class 2 onwards", "Transfer Certificate and previous report card"]],
    "facilities": [["📽️", "LCD Projector Teaching", "Lessons are shown and explained on a projector screen."],
                   ["💻", "Computer Classes", "Computer teaching from Class 1."],
                   ["🚌", "School Bus", "Transport facility is available."],
                   ["🧘", "Yoga & Meditation", "For the mental and physical growth of children."],
                   ["🏫", "Small Classes", "A limited number of students in each classroom."],
                   ["🔬", "Learning by Doing", "Hands-on science experiments and activities."]],
    "activities": [
        ["🎓", "Navodaya & IIT Foundation", "Strong foundation for competitive exams.", ["Navodaya classes along with Class 4 and 5", "IIT foundation teaching from Class 6", "Weekly tests on completed lessons", "Special attention to students who are lagging behind"]],
        ["🗣️", "Spoken English (L.S.R.W)", "Listening, speaking, reading and writing.", ["Communication skills so that students can speak English", "English taught in an easy way", "Builds love for the language", "Regular practice in class"]],
        ["🧮", "Shortcut Maths & Memory", "Faster calculation and a sharper memory.", ["Maths taught with shortcut methods", "Memory techniques to improve memory power", "Weekly tests with results shared with parents", "Maths puzzles and practice"]],
        ["📽️", "Computer & LCD Projector", "Modern teaching tools from the early classes.", ["Computer teaching from Class 1", "Lessons on an LCD projector", "Typing and basic skills", "Safe internet habits"]],
        ["🧘", "Yoga, Meditation & Dance", "For the mental and physical growth of children.", ["Yoga and breathing exercises", "Meditation sessions", "Dance classes", "Annual day performances"]],
        ["🇮🇳", "Hindi Exams", "Prathama and Madhyama preparation.", ["Hindi exams such as Prathama and Madhyama are written", "Guidance from our teachers", "Regular practice", "Certificates for achievers"]],
        ["⚽", "Sports & Games", "Healthy bodies, team spirit and fair play.", ["Athletics and annual sports day", "Kho-kho, kabaddi, cricket, football", "Indoor games and chess", "Inter-house competitions"]],
        ["🎨", "Art & Craft", "Colours, clay and creativity every week.", ["Drawing and painting", "Clay modelling and paper craft", "Best-out-of-waste projects", "Art exhibitions"]],
        ["🎵", "Music", "Singing and instruments for every young voice.", ["Group singing and devotional songs", "Keyboard and percussion basics", "Music competitions", "Morning assembly performances"]],
        ["🔬", "Science Club", "Learning by doing, experimenting and exploring.", ["Hands-on science experiments", "Science exhibition", "Working models", "Science quiz"]],
        ["🌳", "Eco / Nature Club", "Little buds who care for the planet.", ["Tree planting and school garden", "Plastic-free campus drives", "Nature walks", "Environment day programmes"]],
        ["📖", "Library & Reading", "Building a love for books.", ["Weekly library period", "Story-telling sessions", "Book-review and reading challenges", "Spelling bee and recitation"]],
        ["🏆", "Competitions & Quiz", "Platforms to shine and win.", ["Quiz and elocution", "Drawing and handwriting contests", "Inter-school events", "Prize distribution"]],
        ["🎉", "Celebrations & Events", "Festivals and days that bring us together.", ["Independence and Republic Day", "Teachers' Day and Children's Day", "Pongal / Diwali / Christmas celebrations", "Annual Day"]],
    ],
})


DEFAULT_SITE["announcements"] = [
    {"id": "a1", "text": "Admissions are in progress for Nursery to 10th Class. Call 85199 77744 / 92901 11182.", "until": "", "on": True},
    {"id": "a2", "text": "IIT foundation from Class 6  |  Navodaya classes with Class 4 & 5  |  School bus facility available", "until": "", "on": True},
]

DEFAULT_SITE.update({
    "results_history": [], "results_banner_on": True, "calendar": [], "testimonials": [], "bus_routes": [],
    "upi_id": "", "upi_name": "R K Little Buds School", "map_link": "", "show_rank": True,
})

# Older default texts (replaced above). If a saved copy is still identical to the old default, it is refreshed automatically.
OLD_HASHES = {
    "address": "a2971e5937522d9a3a0bf21831500d32",
    "phone": "a48bc97178bed65ab0a0e3c669b3c500",
    "email": "b933250345c153c83ef10e62d8caf9df",
    "hours": "7aad85d46bf7242fd4b19bee0462794a",
    "quote": "77a6409a510da74315dc8f43b17b6720",
    "highlights": "67d08c90f4c250a6bda4c3921875e41b",
    "age_rules": "36c0007a4bf26c5dc545ff8bcdbc9044",
    "activities": "e444a79b10ecfbe378e94db05b558443",
    "facilities": "60449d84bada921e22b854509231abac",
    "about": "440c71eac79d3390cf345fd9768882ee"
}


def migrate_site(c):
    row = c.execute("SELECT v FROM settings WHERE k='site'").fetchone()
    if not row:
        return
    d, changed = json.loads(row[0]), False
    for k, h in OLD_HASHES.items():
        if k in d and hashlib.md5(json.dumps(d[k], sort_keys=True, ensure_ascii=False).encode()).hexdigest() == h:
            del d[k]
            changed = True
    if changed:
        c.execute("UPDATE settings SET v=? WHERE k='site'", (json.dumps(d),))


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    with sqlite3.connect(DB) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS fields(id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT,
                                          label TEXT, type TEXT, options TEXT);
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS parents(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE,
                                           pw TEXT, name TEXT, students TEXT);""")
        try:
            c.execute("ALTER TABLE parents ADD COLUMN must_change INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        migrate_site(c)
        c.executescript('''
        CREATE TABLE IF NOT EXISTS att_daily(sid INTEGER, d TEXT, status TEXT, PRIMARY KEY(sid, d));
        CREATE TABLE IF NOT EXISTS staff_users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, pw TEXT, active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, who TEXT, action TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS class_teachers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, username TEXT UNIQUE COLLATE NOCASE, phone TEXT, pw TEXT, active INTEGER DEFAULT 1, must_change INTEGER DEFAULT 1, last_login TEXT);
        CREATE TABLE IF NOT EXISTS class_teacher_assign(tid INTEGER, cls TEXT, section TEXT, PRIMARY KEY(tid, cls, section));
        CREATE TABLE IF NOT EXISTS notice_reads(nid INTEGER, pid INTEGER, ts TEXT, PRIMARY KEY(nid, pid));
        CREATE TABLE IF NOT EXISTS exam_names(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE COLLATE NOCASE, sort INTEGER DEFAULT 0);''')
        if not c.execute("SELECT 1 FROM exam_names").fetchone():
            c.executemany("INSERT INTO exam_names(name,sort) VALUES(?,?)", [(n, i) for i, n in enumerate(DEFAULT_EXAMS)])
        for (d,) in c.execute("SELECT data FROM records WHERE module='exams'").fetchall():
            nm = (json.loads(d).get("exam") or "").strip()
            if nm and not c.execute("SELECT 1 FROM exam_names WHERE name=?", (nm,)).fetchone():
                c.execute("INSERT INTO exam_names(name,sort) VALUES(?,?)", (nm, 99))
        if not c.execute("SELECT 1 FROM settings WHERE k='pin'").fetchone():
            c.execute("INSERT INTO settings VALUES('pin',?)", (generate_password_hash("admin123"),))
        if not c.execute("SELECT 1 FROM settings WHERE k='staff_pin'").fetchone():
            c.execute("INSERT INTO settings VALUES('staff_pin',?)", (generate_password_hash("staff123"),))
        if not c.execute("SELECT 1 FROM records").fetchone():
            today = date.today().isoformat()
            sample = [
                ("students", dict(name="Aarav Kumar", cls="5", roll="12", parent="Suresh Kumar", phone="9876500001", gender="Male")),
                ("students", dict(name="Divya Sri", cls="3", roll="07", parent="Lakshmi R", phone="9876500002", gender="Female")),
                ("teachers", dict(name="Mrs. Revathi", subject="English", qual="B.Ed, M.A", classes="LKG, UKG, 1-5", show="Yes", phone="9876500010", salary="28000")),
                ("fees", dict(student="Aarav Kumar", cls="5", term="Term 1", due="12000", paid="12000", date=today, mode="UPI")),
                ("fees", dict(student="Divya Sri", cls="3", term="Term 1", due="10000", paid="4000", date=today, mode="Cash")),
                ("admissions", dict(name="Kavin M", cls="LKG", parent="Murugan", phone="9876500020", date=today, status="Interview")),
            ]
            c.executemany("INSERT INTO records(module,data) VALUES(?,?)", [(m, json.dumps(d)) for m, d in sample])


def fields_of(m):
    out = [dict(key=f[0], label=f[1], type=f[2], options=f[3] if len(f) > 3 else [])
           for f in MODULES[m]["fields"]]
    for r in db().execute("SELECT * FROM fields WHERE module=? ORDER BY id", (m,)):
        out.append(dict(key=f"c{r['id']}", label=r["label"], type=r["type"],
                        options=json.loads(r["options"] or "[]"), custom=True, fid=r["id"]))
    if m == "exams":
        for f in out:
            if f["key"] == "exam":
                f["options"] = _exam_names()
    return out


def rows_of(m):
    return [dict(json.loads(r["data"]), id=r["id"])
            for r in db().execute("SELECT * FROM records WHERE module=? ORDER BY id DESC", (m,))]


# ---------- helpers ----------
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def inr(v):
    n = int(round(num(v)))
    s, head, parts = str(abs(n)), "", []
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + "₹" + s


def donut(parts):
    total = sum(p["v"] for p in parts)
    circ, off, arcs = 2 * math.pi * 52, 0, []
    for p in parts:
        if total and p["v"] > 0:
            ln = p["v"] / total * circ
            arcs.append(dict(p, ln=round(ln, 2), gap=round(circ - ln, 2), off=round(-off, 2)))
            off += ln
    return arcs


app.jinja_env.filters.update(inr=inr, num=num)
app.jinja_env.globals["imgurl"] = lambda p: url_for("static", filename=p if p.startswith("img/") else "uploads/" + p)


@app.context_processor
def inject():
    has_logo = os.path.exists(LOGO)
    return dict(SCHOOL=SCHOOL, SITE=get_site(), MODULES=MODULES, LABELS=LABELS, today=date.today().isoformat(),
                role=session.get("role"), user=session.get("user"), is_principal=session.get("role") == "admin",
                has_logo=has_logo, logo_v=int(os.path.getmtime(LOGO)) if has_logo else 0,
                asset_v=int(max((os.path.getmtime(os.path.join(app.static_folder, f)) for f in ("admin.css", "report.css", "login.css") if os.path.exists(os.path.join(app.static_folder, f))), default=0)))


def login_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not session.get("role"):
            flash("Please login to view school data.")
            return redirect(url_for("login"))
        return f(*a, **k)
    return wrapper


def admin_only(f):
    @wraps(f)
    def wrapper(*a, **k):
        if session.get("role") != "admin":
            flash("This page is for the Admin only.")
            return redirect(url_for("dashboard" if session.get("role") else "login"))
        return f(*a, **k)
    return wrapper


# ---------- pages ----------
EVENT_CATEGORIES = ["Activities", "Achievements", "Projects", "Events", "Sports", "Celebrations"]
# Shown on the home-page slider until real photos are uploaded in Admin > Gallery.
SAMPLE_SLIDES = [("img/hero-building.jpg", "Campus", "Our school building"), ("img/life1.png", "Activities", "Hands-on science"),
                 ("img/results.jpg", "Achievements", "SSC results - 100% passed"), ("img/life4.png", "Projects", "Creative craft time"),
                 ("img/life3.png", "Achievements", "Little achievers"), ("img/bus.png", "Facilities", "School bus facility"),
                 ("img/life5.png", "Activities", "Learning together")]


def moment_slides(site, limit=12):
    """Latest school photos for the home-page slider: newest gallery events first."""
    slides = []
    for ev in site.get("events", []):
        imgs = ([ev["cover"]] if ev.get("cover") else []) + list(ev.get("photos", []))
        for p in imgs[:4]:
            slides.append(dict(src="uploads/" + p, cat=ev.get("category") or "Latest", title=ev.get("title", ""), date=ev.get("date", "")))
    if len(slides) < limit:
        for p in reversed(site.get("photos", [])):
            slides.append(dict(src="uploads/" + p, cat="Latest", title="School moments", date=""))
    if not slides:
        slides = [dict(src=s, cat=c, title=t, date="") for s, c, t in SAMPLE_SLIDES]
    return slides[:limit]


def _cat(v):
    v = (v or "").strip()
    return v if v in EVENT_CATEGORIES else "Activities"


@app.route("/")
def home():
    teachers = []
    for t in reversed(rows_of("teachers")):
        if t.get("show") == "Yes":
            teachers.append(dict(name=t.get("name", ""), subject=t.get("subject", ""), qual=t.get("qual", ""),
                                 photo=t.get("photo", ""), classes=expand_classes(t.get("classes"))))
    site = get_site()
    upcoming = sorted(r for r in site.get("calendar", []) if len(r) >= 2 and r[0] >= date.today().isoformat())[:6]
    return render_template("public.html", classes=CLASSES, teachers=teachers, announcements=active_announcements(), upcoming=upcoming,
                           slides=moment_slides(site))


@app.post("/enquiry")
def enquiry():
    f = {k: request.form.get(k, "").strip()[:100] for k in ("name", "cls", "parent", "phone")}
    if request.form.get("website"):  # hidden spam trap
        return redirect(url_for("home"))
    if not (f["name"] and f["parent"] and f["phone"]):
        flash("Please fill in the child's name, parent's name and phone number.")
    else:
        f.update(date=date.today().isoformat(), status="Applied", source="Website")
        db().execute("INSERT INTO records(module,data) VALUES('admissions',?)", (json.dumps(f),))
        db().commit()
        flash("Thank you! Your enquiry was received. Our office will contact you soon.")
    return redirect(url_for("home") + "#admissions")


@app.route("/dashboard")
@login_required
def dashboard():
    S, T, F, A = (rows_of(x) for x in ("students", "teachers", "fees", "admissions"))
    due, paid = sum(num(r.get("due")) for r in F), sum(num(r.get("paid")) for r in F)
    pend, pct = max(due - paid, 0), (round(paid / due * 100) if due else 0)
    stats = [("🎓", "Students", len(S), "#0b4ea2"), ("👩‍🏫", "Teachers", len(T), "#f26522"),
             ("💰", "Fees collected", inr(paid), "#1a8a3a"), ("⏳", "Fees pending", inr(pend), "#ffb300"),
             ("📝", "Admissions", len(A), "#e31e24"), ("📈", "Collection rate", f"{pct}%", "#1b8a8a")]
    gender = Counter(s.get("gender") for s in S)
    modes = Counter()
    for f in F:
        if num(f.get("paid")):
            modes[f.get("mode") or "Other"] += num(f["paid"])
    t = date.today()
    months = []
    for i in range(5, -1, -1):
        y, mo = t.year, t.month - i
        while mo <= 0:
            mo += 12; y -= 1
        key = f"{y}-{mo:02d}"
        months.append((date(y, mo, 1).strftime("%b"),
                       sum(num(f.get("paid")) for f in F if (f.get("date") or "")[:7] == key)))
    mmax = max([v for _, v in months] + [1])
    per_class = [(c, sum(1 for s in S if s.get("cls") == c)) for c in CLASSES]
    cmax = max([n for _, n in per_class] + [1])
    pipeline = [(k, sum(1 for a in A if a.get("status") == k), c) for k, c in
                [("Applied", "#0b4ea2"), ("Interview", "#ffb300"), ("Admitted", "#1a8a3a"), ("Rejected", "#e31e24")]]
    return render_template(
        "dashboard.html", stats=stats, pct=pct, today_long=t.strftime("%A, %d %B %Y"),
        fee_arcs=donut([dict(l="Collected", v=paid, c="#1a8a3a", f=inr(paid)), dict(l="Pending", v=pend, c="#ffb300", f=inr(pend))]),
        gender_arcs=donut([dict(l="Boys", v=gender["Male"], c="#0b4ea2", f=gender["Male"]), dict(l="Girls", v=gender["Female"], c="#f26522", f=gender["Female"])]),
        mode_arcs=donut([dict(l=k, v=v, c=PALETTE[i % 7], f=inr(v)) for i, (k, v) in enumerate(modes.items())]),
        paid=inr(paid), n_students=len(S), months=months, mmax=mmax,
        per_class=per_class, cmax=cmax, pipeline=pipeline, pmax=max([p[1] for p in pipeline] + [1]),
        weak=weak_pins() if session.get("role") == "admin" else [], an=dash_analytics(),
        followups=sorted([a for a in A if a.get("callback") and a["callback"] <= t.isoformat() and a.get("status") in ("Applied", "Interview")], key=lambda a: a["callback"])[:8],
        birthdays=[s for s in S if len(s.get("dob") or "") >= 10 and s["dob"][5:10] == t.isoformat()[5:10]])


@app.route("/m/<m>")
@login_required
def listing(m):
    if m not in MODULES:
        abort(404)
    q, cls = request.args.get("q", "").lower(), request.args.get("cls", "")
    flds = fields_of(m)
    rows = [r for r in rows_of(m)
            if (not q or q in json.dumps(r).lower())
            and (not cls or r.get("cls") == cls or cls in expand_classes(r.get("classes")))]
    cols = MODULES[m]["cols"] + [f["key"] for f in flds if f.get("custom")]
    names = {f["key"]: f["label"] for f in flds}
    snames = {str(r["id"]): r.get("name", "") for r in rows_of("students")}
    return render_template("list.html", m=m, mod=MODULES[m], rows=rows, cols=cols, names=names, snames=snames,
                           q=request.args.get("q", ""), cls=cls, classes=CLASSES + ["Alumni"],
                           can_edit=session.get("role") == "admin" or m in EDIT_OPEN,
                           reads=Counter(x["nid"] for x in db().execute("SELECT nid FROM notice_reads")) if m == "notices" else {},
                           has_cls=any(f["key"] in ("cls", "classes", "sid") for f in flds))


@app.route("/m/<m>/new", methods=["GET", "POST"])
@app.route("/m/<m>/<int:rid>/edit", methods=["GET", "POST"])
@login_required
def form(m, rid=None):
    if m not in MODULES:
        abort(404)
    if rid and session.get("role") != "admin" and m not in EDIT_OPEN:
        flash("Only the Admin can edit records.")
        return redirect(url_for("listing", m=m))
    flds = fields_of(m)
    row = db().execute("SELECT * FROM records WHERE id=? AND module=?", (rid, m)).fetchone() if rid else None
    data = json.loads(row["data"]) if row else {}
    if request.method == "POST":
        prev, data = data, {}
        for f in flds:
            k = f["key"]
            if f["type"] == "photo":
                up, old = request.files.get(k), prev.get(k, "")
                if _is_img(up):
                    _rm(old)
                    data[k] = _save_img(up, m)
                elif request.form.get(k + "_clear"):
                    _rm(old)
                    data[k] = ""
                else:
                    data[k] = old
            else:
                data[k] = request.form.get(k, "").strip()
        for k, v in prev.items():
            data.setdefault(k, v)
        if any(f["type"] == "student" for f in flds):
            sd = str(data.get("sid", ""))
            st = db().execute("SELECT * FROM records WHERE id=? AND module='students'", (int(sd) if sd.isdigit() else 0,)).fetchone()
            if st is None:
                flash("Please choose a student.")
                return redirect(request.url)
            data["student"], data["cls"] = json.loads(st["data"]).get("name", ""), json.loads(st["data"]).get("cls", "")
        if rid:
            db().execute("UPDATE records SET data=? WHERE id=?", (json.dumps(data), rid))
            sid = rid
        else:
            sid = db().execute("INSERT INTO records(module,data) VALUES(?,?)", (m, json.dumps(data))).lastrowid
        db().commit()
        audit("Updated" if rid else "Added", f"{MODULES[m]['title']} #{sid}")
        if m == "students" and sid not in _linked_student_ids():
            flash(auto_parent_login(sid, data))
        if request.args.get("next") == "profile" and data.get("sid"):
            return redirect(url_for("student_profile", sid=data["sid"]))
        return redirect(url_for("listing", m=m))
    return render_template("form.html", m=m, mod=MODULES[m], fields=flds, data=data, editing=bool(rid),
                           students=_student_options(), prefill=request.args.get("sid", ""))


@app.post("/m/<m>/<int:rid>/delete")
@admin_only
def delete(m, rid):
    db().execute("DELETE FROM records WHERE id=? AND module=?", (rid, m))
    db().commit()
    audit("Deleted", f"{MODULES[m]['title']} #{rid}")
    return redirect(request.referrer or url_for("listing", m=m))


@app.route("/m/<m>/export.csv")
@login_required
def export(m):
    if m not in MODULES:
        abort(404)
    flds, buf = fields_of(m), io.StringIO()
    w = csv.writer(buf)
    snm = {str(x["id"]): x.get("name", "") for x in rows_of("students")}
    w.writerow([f["label"] for f in flds])
    for r in rows_of(m):
        w.writerow([snm.get(str(r.get(f["key"])), r.get("student", "")) if f["type"] == "student" else r.get(f["key"], "") for f in flds])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={m}.csv"})


# ---------- principal login ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    want = "admin" if request.values.get("as") == "admin" else "staff"      # which tab the user chose
    if request.method == "GET" and session.get("role"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        pin, key = request.form.get("pin", ""), f"staff:{request.remote_addr}"
        if locked(key):
            flash("Too many wrong attempts. Please wait 10 minutes and try again.")
            return render_template("login.html", want=want)
        st = {r["k"]: r["v"] for r in db().execute("SELECT * FROM settings")}
        tu = next((u for u in db().execute("SELECT * FROM staff_users WHERE active=1") if check_password_hash(u["pw"], pin)), None)
        if check_password_hash(st["pin"], pin):
            session["role"], session["user"] = "admin", "Admin"
        elif want == "admin":                      # Admin tab: only the Admin PIN is accepted
            note_fail(key)
            flash("Wrong Admin PIN. Please try again.")
            return render_template("login.html", want=want)
        elif tu is not None:
            session["role"], session["user"] = "staff", tu["name"]
        elif check_password_hash(st["staff_pin"], pin):
            session["role"], session["user"] = "staff", "Staff"
        else:
            note_fail(key)
            flash("Wrong PIN. Please try again.")
            return render_template("login.html", want=want)
        FAILS.pop(key, None)
        audit("Login")
        return redirect(url_for("dashboard"))
    return render_template("login.html", want=want)


@app.route("/logout")
def logout():
    session.pop("role", None)
    session.pop("user", None)
    return redirect(url_for("home"))


@app.route("/principal")
@admin_only
def principal():
    custom = {m: [f for f in fields_of(m) if f.get("custom")] for m in MODULES}
    return render_template("principal.html", custom=custom, base_fields={m: MODULES[m]["fields"] for m in MODULES})


@app.post("/principal/field")
@admin_only
def add_field():
    m, label = request.form["module"], request.form["label"].strip()
    ftype = request.form["type"]
    opts = [o.strip() for o in request.form.get("options", "").split(",") if o.strip()]
    if m not in MODULES or not label or (ftype == "select" and not opts):
        flash("Enter a field name (and options for a dropdown).")
    else:
        db().execute("INSERT INTO fields(module,label,type,options) VALUES(?,?,?,?)", (m, label, ftype, json.dumps(opts)))
        db().commit()
    return redirect(url_for("principal"))


@app.post("/principal/field/<int:fid>/delete")
@admin_only
def delete_field(fid):
    db().execute("DELETE FROM fields WHERE id=?", (fid,))
    db().commit()
    return redirect(url_for("principal"))


@app.post("/principal/pin")
@admin_only
def change_pin():
    pin = request.form.get("pin", "")
    key = "staff_pin" if request.form.get("which") == "staff" else "pin"
    if len(pin) < 4:
        flash("PIN must have at least 4 characters.")
    else:
        db().execute("UPDATE settings SET v=? WHERE k=?", (generate_password_hash(pin), key))
        db().commit()
        flash("PIN changed.")
    return redirect(url_for("principal"))


@app.route("/principal/backup")
@admin_only
def backup():
    data = {"records": [dict(r) for r in db().execute("SELECT * FROM records")],
            "fields": [dict(r) for r in db().execute("SELECT * FROM fields")]}
    return Response(json.dumps(data, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=rk-little-buds-backup.json"})


# ---------- website editor (Admin) ----------
def get_site():
    site = dict(DEFAULT_SITE)
    try:
        row = db().execute("SELECT v FROM settings WHERE k='site'").fetchone()
        if row:
            stored = json.loads(row["v"])
            site.update(stored)
            site["images"] = {**DEFAULT_SITE["images"], **stored.get("images", {})}
    except Exception:
        pass
    return site


def save_site(patch):
    row = db().execute("SELECT v FROM settings WHERE k='site'").fetchone()
    cur = json.loads(row["v"]) if row else {}
    cur.update(patch)
    db().execute("INSERT OR REPLACE INTO settings VALUES('site',?)", (json.dumps(cur),))
    db().commit()


def _int(v):
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return 0


def _lines(t):
    return [l.strip() for l in (t or "").splitlines() if l.strip()]


def _rows(t, n):
    out = []
    for l in _lines(t):
        p = [x.strip() for x in l.split("|")]
        out.append((p + [""] * n)[:n])
    return out


def _pipe(rows):
    return "\n".join(" | ".join(str(x) for x in r) for r in rows)


@app.route("/principal/website", methods=["GET", "POST"])
@admin_only
def website_editor():
    if request.method == "POST":
        f = request.form
        patch = {k: f.get(k, "").strip()[:300] for k in ("quote", "motto", "address", "phone", "email", "hours")}
        patch.update({k: f.get(k, "").strip()[:300] for k in ("quote_en", "recognised", "range_te", "range_en", "campus_te", "campus_en",
                                                              "campus1_cap", "campus2_cap", "bus_te", "bus_en", "bus_text", "success_te", "success_en")})
        patch["telugu_motto"] = [r for r in _rows(f.get("telugu_motto"), 2) if r[0]]
        patch["badges"] = [r for r in _rows(f.get("badges"), 2) if r[0]]
        patch["specialities"] = [r for r in _rows(f.get("specialities"), 2) if r[0]]
        patch["campuses"] = [r for r in _rows(f.get("campuses"), 4) if r[0]]
        patch["about_te"] = [x.strip() for x in re.split(r"\n\s*\n", f.get("about_te", "")) if x.strip()]
        patch["results"] = {k: _int(f.get("res_" + k)) for k in ("total", "passed", "a500", "a400", "b400")}
        patch["results"]["caption"] = f.get("res_caption", "").strip()[:200]
        patch.update({k: f.get(k, "").strip()[:300] for k in ("upi_id", "upi_name", "map_link")})
        patch["show_rank"], patch["results_banner_on"] = bool(f.get("show_rank")), bool(f.get("results_banner_on"))
        patch["results_history"] = [r for r in _rows(f.get("results_history"), 6) if r[0]]
        patch["calendar"] = [r for r in _rows(f.get("calendar"), 3) if r[0] and r[1]]
        patch["testimonials"] = [r for r in _rows(f.get("testimonials"), 2) if r[1]]
        patch["bus_routes"] = [r for r in _rows(f.get("bus_routes"), 3) if r[0]]
        patch["about"] = [x.strip() for x in re.split(r"\n\s*\n", f.get("about", "")) if x.strip()]
        for k in ("vision", "mission", "documents"):
            patch[k] = _lines(f.get(k))
        patch["highlights"] = _rows(f.get("highlights"), 2)
        patch["admission_steps"] = _rows(f.get("steps"), 2)
        patch["age_rules"] = _rows(f.get("rules"), 2)
        patch["facilities"] = [r for r in _rows(f.get("facilities"), 3) if r[1]]
        patch["gallery"] = [[r[0], r[1] or "#7b2d8e", r[2] or "#b46bc9"] for r in _rows(f.get("gallery"), 3) if r[0]]
        patch["activities"] = [[r[0] or "⭐", r[1], r[2], [x.strip() for x in r[3].split(";") if x.strip()]]
                               for r in _rows(f.get("activities"), 4) if r[1]]
        save_site(patch)
        audit("Website edited")
        flash("Website updated. Your changes are live.")
        return redirect(url_for("website_editor"))
    s = get_site()
    t = dict(results_history=_pipe(s["results_history"]), calendar=_pipe(s["calendar"]), testimonials=_pipe(s["testimonials"]),
             bus_routes=_pipe(s["bus_routes"]), about="\n\n".join(s["about"]), about_te="\n\n".join(s["about_te"]), telugu_motto=_pipe(s["telugu_motto"]),
             badges=_pipe(s["badges"]), specialities=_pipe(s["specialities"]), campuses=_pipe(s["campuses"]), vision="\n".join(s["vision"]), mission="\n".join(s["mission"]),
             documents="\n".join(s["documents"]), highlights=_pipe(s["highlights"]), steps=_pipe(s["admission_steps"]),
             rules=_pipe(s["age_rules"]), facilities=_pipe(s["facilities"]), gallery=_pipe(s["gallery"]),
             activities="\n".join(f"{a[0]} | {a[1]} | {a[2]} | {'; '.join(a[3])}" for a in s["activities"]))
    return render_template("website_editor.html", s=s, t=t)


@app.post("/principal/website/reset")
@admin_only
def website_reset():
    keep = {k: v for k, v in get_site().items() if k in ("photos", "events", "about_people", "images", "announcements") and v}
    keep["images"] = {k: v for k, v in keep.get("images", {}).items() if DEFAULT_SITE["images"].get(k) != v}
    db().execute("DELETE FROM settings WHERE k='site'")
    db().commit()
    if keep:
        save_site(keep)
    flash("Website text restored to the defaults (photos, gallery events and leadership messages kept).")
    return redirect(url_for("website_editor"))


def _ext(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


@app.post("/principal/website/image/<key>")
@admin_only
def upload_site_image(key):
    if key not in DEFAULT_SITE["images"]:
        abort(404)
    f = request.files.get("file")
    if _is_img(f):
        row = db().execute("SELECT v FROM settings WHERE k='site'").fetchone()
        imgs = json.loads(row["v"]).get("images", {}) if row else {}
        old = imgs.get(key)
        imgs[key] = _save_img(f, "site")
        save_site({"images": imgs})
        if old and not old.startswith("img/"):
            _rm(old)
        flash("Image updated.")
    else:
        flash("Please choose a PNG, JPG or WEBP image.")
    return redirect(url_for("website_editor"))


@app.post("/principal/website/image/<key>/reset")
@admin_only
def reset_site_image(key):
    row = db().execute("SELECT v FROM settings WHERE k='site'").fetchone()
    imgs = json.loads(row["v"]).get("images", {}) if row else {}
    old = imgs.pop(key, None)
    save_site({"images": imgs})
    if old and not old.startswith("img/"):
        _rm(old)
    flash("Original image restored.")
    return redirect(url_for("website_editor"))


@app.post("/principal/website/logo")
@admin_only
def upload_logo():
    f = request.files.get("logo")
    if f and f.filename and _ext(f.filename) in IMG_EXT:
        f.save(LOGO)
        flash("Logo updated.")
    else:
        flash("Please choose a PNG, JPG or WEBP image.")
    return redirect(url_for("website_editor"))


@app.post("/principal/website/logo/remove")
@admin_only
def remove_logo():
    if os.path.exists(LOGO):
        os.remove(LOGO)
    flash("Logo removed.")
    return redirect(url_for("website_editor"))


@app.post("/principal/website/photo")
@admin_only
def upload_photo():
    os.makedirs(UPLOADS, exist_ok=True)
    photos, n = list(get_site().get("photos", [])), 0
    for f in request.files.getlist("photos"):
        if f and f.filename and _ext(f.filename) in IMG_EXT:
            name = f"g{int(time.time() * 1000)}{n}.{_ext(f.filename)}"
            f.save(os.path.join(UPLOADS, name))
            photos.append(name)
            n += 1
    save_site({"photos": photos})
    flash(f"{n} photo(s) added to the gallery." if n else "Please choose PNG, JPG or WEBP images.")
    return redirect(url_for("website_editor"))


@app.post("/principal/website/photo/<name>/delete")
@admin_only
def delete_photo(name):
    photos = list(get_site().get("photos", []))
    if name in photos:
        photos.remove(name)
        save_site({"photos": photos})
        try:
            os.remove(os.path.join(UPLOADS, name))
        except OSError:
            pass
    return redirect(url_for("website_editor"))


# ---------- class helper + gallery events ----------
def expand_classes(text):
    """'LKG, UKG, 1-3, class 5' -> ['LKG','UKG','1','2','3','5']  ('all' = every class)"""
    out = []
    for tok in re.split(r"[,;/]", text or ""):
        tok = re.sub(r"(?i)class\s*", "", tok).strip().upper()
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", tok)
        if tok in ("ALL", "ALL CLASSES"):
            out += [c.upper() for c in CLASSES]
        elif m:
            out += [str(i) for i in range(int(m[1]), int(m[2]) + 1)]
        elif tok:
            out.append(tok)
    canon = {c.upper(): c for c in CLASSES}
    return [canon[c] for c in dict.fromkeys(out) if c in canon]


def _is_img(f):
    return bool(f and f.filename and _ext(f.filename) in IMG_EXT)


def _is_video(f):
    return bool(f and f.filename and _ext(f.filename) in VIDEO_EXT)


def _save_img(f, sub):
    os.makedirs(os.path.join(UPLOADS, sub), exist_ok=True)
    ext = _ext(f.filename)
    name = f"{sub}/{uuid.uuid4().hex[:12]}.{ext}"
    path, saved = os.path.join(UPLOADS, name), False
    if ext in ("jpg", "jpeg", "png", "webp"):
        try:                                   # shrink big photos so pages load fast on mobile data
            from PIL import Image, ImageOps
            f.stream.seek(0)
            im = ImageOps.exif_transpose(Image.open(f.stream))
            if max(im.size) > 1600:
                im.thumbnail((1600, 1600))
            if ext in ("jpg", "jpeg"):
                im.convert("RGB").save(path, "JPEG", quality=84, optimize=True)
            else:
                im.save(path, optimize=True)
            saved = True
        except Exception:
            f.stream.seek(0)
    if not saved:
        f.save(path)
    return name


def _rm(path):
    if path and ".." not in path:
        try:
            os.remove(os.path.join(UPLOADS, path))
        except OSError:
            pass


def _events():
    return list(get_site().get("events", []))


def _find_event(events, eid):
    ev = next((e for e in events if e["id"] == eid), None)
    if ev is None:
        abort(404)
    return ev


@app.route("/principal/gallery", methods=["GET", "POST"])
@admin_only
def gallery_admin():
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:120]
        if not title:
            flash("Please enter the event name.")
            return redirect(url_for("gallery_admin"))
        ev = dict(id=uuid.uuid4().hex[:8], title=title, category=_cat(request.form.get("category")), icon=request.form.get("icon", "").strip()[:8] or "🎉",
                  date=request.form.get("date", "").strip()[:60], details=request.form.get("details", "").strip()[:3000],
                  cover="", photos=[])
        if _is_img(request.files.get("cover")):
            ev["cover"] = _save_img(request.files["cover"], "events")
        ev["photos"] = [_save_img(f, "events") for f in request.files.getlist("photos") if _is_img(f)]
        ev["videos"] = [_save_img(f, "events") for f in request.files.getlist("videos") if _is_video(f)]
        events = _events()
        events.insert(0, ev)
        save_site({"events": events})
        flash("Event added to the gallery.")
        return redirect(url_for("gallery_admin"))
    return render_template("gallery_admin.html", events=_events(), cats=EVENT_CATEGORIES)


@app.route("/principal/gallery/<eid>", methods=["GET", "POST"])
@admin_only
def gallery_edit(eid):
    events = _events()
    ev = _find_event(events, eid)
    if request.method == "POST":
        ev["title"] = request.form.get("title", "").strip()[:120] or ev["title"]
        ev["icon"] = request.form.get("icon", "").strip()[:8] or "🎉"
        ev["date"] = request.form.get("date", "").strip()[:60]
        ev["category"] = _cat(request.form.get("category"))
        ev["details"] = request.form.get("details", "").strip()[:3000]
        if _is_img(request.files.get("cover")):
            _rm(ev.get("cover"))
            ev["cover"] = _save_img(request.files["cover"], "events")
        ev["photos"] += [_save_img(f, "events") for f in request.files.getlist("photos") if _is_img(f)]
        ev["videos"] = ev.get("videos", []) + [_save_img(f, "events") for f in request.files.getlist("videos") if _is_video(f)]
        save_site({"events": events})
        flash("Event saved.")
        return redirect(url_for("gallery_edit", eid=eid))
    return render_template("gallery_edit.html", ev=ev, cats=EVENT_CATEGORIES)


@app.post("/principal/gallery/<eid>/photo/delete")
@admin_only
def gallery_photo_delete(eid):
    events = _events()
    ev, p = _find_event(events, eid), request.form.get("p", "")
    if p in ev["photos"]:
        ev["photos"].remove(p)
        _rm(p)
        save_site({"events": events})
    return redirect(url_for("gallery_edit", eid=eid))


@app.post("/principal/gallery/<eid>/video/delete")
@admin_only
def gallery_video_delete(eid):
    events = _events()
    ev, v = _find_event(events, eid), request.form.get("p", "")
    if v in ev.get("videos", []):
        ev["videos"].remove(v)
        _rm(v)
        save_site({"events": events})
    return redirect(url_for("gallery_edit", eid=eid))


@app.post("/principal/gallery/<eid>/cover/remove")
@admin_only
def gallery_cover_remove(eid):
    events = _events()
    ev = _find_event(events, eid)
    _rm(ev.get("cover"))
    ev["cover"] = ""
    save_site({"events": events})
    return redirect(url_for("gallery_edit", eid=eid))


@app.post("/principal/gallery/<eid>/delete")
@admin_only
def gallery_delete(eid):
    events = _events()
    ev = _find_event(events, eid)
    for p in ev["photos"] + ev.get("videos", []) + [ev.get("cover")]:
        _rm(p)
    save_site({"events": [e for e in events if e["id"] != eid]})
    flash("Event deleted.")
    return redirect(url_for("gallery_admin"))


# ---------- login throttle (protects PINs from guessing) ----------
FAILS = {}


def locked(key):
    n, t = FAILS.get(key, (0, 0))
    if time.time() - t >= 600:
        FAILS.pop(key, None)
        return False
    return n >= 5


def note_fail(key):
    n, _ = FAILS.get(key, (0, 0))
    FAILS[key] = (n + 1, time.time())


# ---------- parent portal ----------
def default_parent_pin():
    row = db().execute("SELECT v FROM settings WHERE k='parent_default_pin'").fetchone()
    return row["v"] if row else "parent123"


def parent_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        row = db().execute("SELECT must_change FROM parents WHERE id=?", (session.get("parent"),)).fetchone()
        if not session.get("parent") or row is None:
            session.pop("parent", None)
            return redirect(url_for("parent_login"))
        if row["must_change"] and request.endpoint != "parent_password":
            flash("Welcome! Please set your own new password to continue.")
            return redirect(url_for("parent_password"))
        return f(*a, **k)
    return wrapper


def _students_by_ids(ids):
    out = []
    for sid in ids:
        r = db().execute("SELECT * FROM records WHERE id=? AND module='students'", (sid,)).fetchone()
        if r:
            out.append(dict(json.loads(r["data"]), id=r["id"]))
    return out


@app.route("/parent/login", methods=["GET", "POST"])
def parent_login():
    if request.method == "GET" and session.get("parent"):
        return redirect(url_for("parent_home"))
    if request.method == "POST":
        key = f"parent:{request.remote_addr}"
        if locked(key):
            flash("Too many wrong attempts. Please wait 10 minutes and try again.")
            return render_template("parent_login.html")
        u = request.form.get("username", "").strip().lower()
        if re.fullmatch(r"[\d\s+\-()]+", u):
            u = norm_phone(u)
        row = db().execute("SELECT * FROM parents WHERE username=?", (u,)).fetchone()
        if row and check_password_hash(row["pw"], request.form.get("pin", "")):
            FAILS.pop(key, None)
            session["parent"] = row["id"]
            return redirect(url_for("parent_home"))
        note_fail(key)
        flash("Wrong username or PIN.")
    return render_template("parent_login.html")


@app.route("/parent/logout")
def parent_logout():
    session.pop("parent", None)
    return redirect(url_for("home"))


@app.route("/parent/password", methods=["GET", "POST"])
@parent_required
def parent_password():
    p = db().execute("SELECT * FROM parents WHERE id=?", (session["parent"],)).fetchone()
    if request.method == "POST":
        cur, new, again = (request.form.get(k, "") for k in ("current", "new", "again"))
        if not check_password_hash(p["pw"], cur):
            flash("The current password is wrong.")
        elif len(new) < 4:
            flash("The new password must have at least 4 characters.")
        elif new != again:
            flash("The two new passwords do not match.")
        elif new in (cur, default_parent_pin()):
            flash("Please choose a new password that is different from the old one and the default.")
        else:
            db().execute("UPDATE parents SET pw=?, must_change=0 WHERE id=?", (generate_password_hash(new), p["id"]))
            db().commit()
            flash("Your password was changed.")
            return redirect(url_for("parent_home"))
    return render_template("parent_password.html", forced=bool(p["must_change"]))


@app.route("/parent")
@parent_required
def parent_home():
    p = db().execute("SELECT * FROM parents WHERE id=?", (session["parent"],)).fetchone()
    kids = _students_by_ids(json.loads(p["students"] or "[]"))
    flds, fees_all = fields_of("students"), rows_of("fees")
    teachers_all = [t for t in reversed(rows_of("teachers")) if t.get("show") == "Yes"]
    cards = []
    for kid in kids:
        nm = (kid.get("name") or "").strip().lower()
        fees = [f for f in fees_all if (f.get("student") or "").strip().lower() == nm]
        due, paid = sum(num(f.get("due")) for f in fees), sum(num(f.get("paid")) for f in fees)
        cards.append(dict(kid=kid, fees=fees, due=due, paid=paid, bal=max(due - paid, 0), report=child_report(kid),
                          info=[(f["label"], kid.get(f["key"])) for f in flds
                                if kid.get(f["key"]) and f["key"] not in ("name", "cls", "roll")],
                          teachers=[t for t in teachers_all if kid.get("cls") in expand_classes(t.get("classes"))]))
    tot = dict(due=sum(c["due"] for c in cards), paid=sum(c["paid"] for c in cards), bal=sum(c["bal"] for c in cards))
    classes = {c["kid"].get("cls") for c in cards}
    notices = sorted([n for n in rows_of("notices") if n.get("audience") in ("All classes", "", None) or n.get("audience") in classes],
                     key=lambda n: (n.get("date") or "", n["id"]), reverse=True)[:12]
    return render_template("parent.html", p=p, cards=cards, tot=tot, notices=notices,
                           read_ids={r["nid"] for r in db().execute("SELECT nid FROM notice_reads WHERE pid=?", (p["id"],))})


# ---------- Admin: manage parent logins ----------
def _student_options():
    return sorted(rows_of("students"), key=lambda r: (r.get("cls") or "", (r.get("name") or "").lower()))


def _ids():
    return [int(x) for x in request.form.getlist("students") if x.isdigit()]


@app.route("/principal/parents", methods=["GET", "POST"])
@admin_only
def parents_admin():
    if request.method == "POST":
        ids = _ids()
        if not ids:
            flash("Please select at least one student.")
            return redirect(url_for("parents_admin"))
        studs = _students_by_ids(ids)
        username = re.sub(r"\s+", "", request.form.get("username", "").lower())
        if not username and studs:
            username = norm_phone(studs[0].get("phone", ""))
        username = username or "parent" + secrets.token_hex(2)
        typed = request.form.get("pin", "").strip()
        pin = typed or default_parent_pin()
        if len(pin) < 4:
            flash("PIN must have at least 4 characters.")
            return redirect(url_for("parents_admin"))
        name = request.form.get("name", "").strip()[:100] or (studs[0].get("parent", "") if studs else "")
        try:
            db().execute("INSERT INTO parents(username,pw,name,students,must_change) VALUES(?,?,?,?,?)",
                         (username, generate_password_hash(pin), name, json.dumps(ids), 0 if typed else 1))
            db().commit()
            flash(f"Parent login created.  Username: {username}   Password: {pin}   - please share these with the parent."
                  + ("" if typed else "  (The parent will be asked to set a new password at the first login.)"))
        except sqlite3.IntegrityError:
            flash("That username is already used. Please choose another.")
        return redirect(url_for("parents_admin"))
    plist = [dict(id=p["id"], username=p["username"], name=p["name"],
                  kids=_students_by_ids(json.loads(p["students"] or "[]")))
             for p in db().execute("SELECT * FROM parents ORDER BY id DESC")]
    return render_template("parents_admin.html", plist=plist, students=_student_options(), default_pin=default_parent_pin())


@app.route("/principal/parents/<int:pid>", methods=["GET", "POST"])
@admin_only
def parent_edit(pid):
    p = db().execute("SELECT * FROM parents WHERE id=?", (pid,)).fetchone()
    if p is None:
        abort(404)
    if request.method == "POST":
        ids = _ids()
        username = re.sub(r"\s+", "", request.form.get("username", "").lower()) or p["username"]
        pw, newpin, mc = p["pw"], request.form.get("pin", "").strip(), p["must_change"]
        if request.form.get("reset_default"):
            newpin, mc = default_parent_pin(), 1
            pw = generate_password_hash(newpin)
        elif newpin:
            if len(newpin) < 4:
                flash("PIN must have at least 4 characters.")
                return redirect(url_for("parent_edit", pid=pid))
            pw, mc = generate_password_hash(newpin), 0
        try:
            db().execute("UPDATE parents SET username=?, pw=?, name=?, students=?, must_change=? WHERE id=?",
                         (username, pw, request.form.get("name", "").strip()[:100], json.dumps(ids), mc, pid))
            db().commit()
        except sqlite3.IntegrityError:
            flash("That username is already used. Please choose another.")
            return redirect(url_for("parent_edit", pid=pid))
        flash("Parent login saved." + (f"  New password: {newpin}  - please share it with the parent." if newpin else "")
              + ("  (The parent will be asked to set a new password at the next login.)" if newpin and mc else ""))
        return redirect(url_for("parents_admin"))
    return render_template("parent_edit.html", p=p, ids=json.loads(p["students"] or "[]"), students=_student_options())


@app.post("/principal/parents/default")
@admin_only
def parent_default():
    v = request.form.get("pin", "").strip()
    if len(v) < 4:
        flash("The default password must have at least 4 characters.")
    else:
        db().execute("INSERT OR REPLACE INTO settings VALUES('parent_default_pin',?)", (v,))
        db().commit()
        flash("Default parent password updated. It is used for new parent logins when no password is typed.")
    return redirect(url_for("parents_admin"))


@app.post("/principal/parents/<int:pid>/delete")
@admin_only
def parent_delete(pid):
    db().execute("DELETE FROM parents WHERE id=?", (pid,))
    db().commit()
    flash("Parent login deleted.")
    return redirect(url_for("parents_admin"))


# ---------- About school: management / principal / head master / teachers ----------
@app.route("/principal/about", methods=["GET", "POST"])
@admin_only
def about_admin():
    people = [dict(b) for b in get_site().get("about_people", [])]
    if request.method == "POST":
        f, out = request.form, []
        for b in people:
            i = b["id"]
            if f.get("del_" + i):
                _rm(b.get("photo"))
                continue
            b["role"] = f.get("role_" + i, "").strip()[:60] or b["role"]
            b["name"] = f.get("name_" + i, "").strip()[:120]
            b["icon"] = f.get("icon_" + i, "").strip()[:8] or "⭐"
            b["message"] = f.get("msg_" + i, "").strip()[:3000]
            up = request.files.get("photo_" + i)
            if _is_img(up):
                _rm(b.get("photo"))
                b["photo"] = _save_img(up, "people")
            elif f.get("clear_" + i):
                _rm(b.get("photo"))
                b["photo"] = ""
            try:
                b["_o"] = float(f.get("ord_" + i, "999"))
            except ValueError:
                b["_o"] = 999
            out.append(b)
        if f.get("new_role", "").strip():
            nb = dict(id=uuid.uuid4().hex[:8], role=f["new_role"].strip()[:60], name=f.get("new_name", "").strip()[:120],
                      icon=f.get("new_icon", "").strip()[:8] or "⭐", message=f.get("new_msg", "").strip()[:3000],
                      photo="", _o=999)
            if _is_img(request.files.get("new_photo")):
                nb["photo"] = _save_img(request.files["new_photo"], "people")
            out.append(nb)
        out.sort(key=lambda b: b.pop("_o"))
        save_site({"about_people": out})
        flash("About school section saved. Your changes are live.")
        return redirect(url_for("about_admin"))
    return render_template("about_admin.html", people=people)


# ---------- automatic parent login when a student is saved ----------
def norm_phone(s):
    d = re.sub(r"\D", "", s or "")
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d


def _linked_student_ids():
    ids = set()
    for p in db().execute("SELECT students FROM parents"):
        ids.update(json.loads(p["students"] or "[]"))
    return ids


def auto_parent_login(sid, data):
    """Username = mobile number, password = default parent password. Returns a message for staff."""
    username = norm_phone(data.get("phone", ""))
    if not 7 <= len(username) <= 15:
        return "No parent login was created. Enter a valid mobile number in the student's record to create one automatically."
    row = db().execute("SELECT * FROM parents WHERE username=?", (username,)).fetchone()
    if row:
        ids = json.loads(row["students"] or "[]")
        if sid not in ids:
            ids.append(sid)
            db().execute("UPDATE parents SET students=? WHERE id=?", (json.dumps(ids), row["id"]))
            db().commit()
        return f"This mobile number already has a parent login, so the student was added to it (username {username}, brothers/sisters share one login)."
    pin = default_parent_pin()
    db().execute("INSERT INTO parents(username,pw,name,students,must_change) VALUES(?,?,?,?,1)",
                 (username, generate_password_hash(pin), (data.get("parent") or "")[:100], json.dumps([sid])))
    db().commit()
    return f"Parent login created automatically.  Username: {username}   Password: {pin}   (the parent sets a new password at the first login)"


@app.post("/principal/parents/auto")
@admin_only
def parents_auto():
    linked, made, joined, skipped = _linked_student_ids(), 0, 0, 0
    for r in reversed(rows_of("students")):
        if r["id"] in linked:
            continue
        msg = auto_parent_login(r["id"], r)
        if msg.startswith("No parent login"):
            skipped += 1
        elif msg.startswith("This mobile"):
            joined += 1
        else:
            made += 1
    flash(f"Done. {made} new parent login(s) created, {joined} student(s) added to an existing login, {skipped} skipped (no valid mobile number).")
    return redirect(url_for("parents_admin"))


# ---------- scrolling announcements (Staff and Admin can edit) ----------
def _announcements():
    return [dict(a) for a in get_site().get("announcements", [])]


def active_announcements():
    today = date.today().isoformat()
    return [a["text"] for a in get_site().get("announcements", [])
            if a.get("on", True) and a.get("text") and (not a.get("until") or a["until"] >= today)]


@app.route("/announcements", methods=["GET", "POST"])
@login_required
def announce():
    if request.method == "POST":
        text = request.form.get("text", "").strip()[:300]
        if not text:
            flash("Please type the announcement first.")
            return redirect(url_for("announce"))
        items = _announcements()
        items.insert(0, dict(id=uuid.uuid4().hex[:8], text=text, until=request.form.get("until", "").strip()[:10], on=True))
        save_site({"announcements": items})
        audit("Announcement added", text[:80])
        flash("Announcement added. It is now scrolling on the website.")
        return redirect(url_for("announce"))
    return render_template("announce.html", items=_announcements())


@app.post("/announcements/<aid>/save")
@login_required
def announce_save(aid):
    items = _announcements()
    a = next((x for x in items if x["id"] == aid), None)
    if a is None:
        abort(404)
    a["text"] = request.form.get("text", "").strip()[:300] or a["text"]
    a["until"] = request.form.get("until", "").strip()[:10]
    a["on"] = bool(request.form.get("on"))
    save_site({"announcements": items})
    flash("Announcement saved.")
    return redirect(url_for("announce"))


@app.post("/announcements/<aid>/delete")
@login_required
def announce_delete(aid):
    save_site({"announcements": [a for a in _announcements() if a["id"] != aid]})
    flash("Announcement deleted.")
    return redirect(url_for("announce"))


# ---------- student progress: exams, marks, activities, competitive exams, attendance, remarks ----------
EDIT_OPEN = {"exams", "activities", "competitive", "remarks", "attendance", "notices", "feedback"}   # Staff may add AND edit these
app.jinja_env.filters["n"] = lambda v: "%g" % num(v)


def _get_student(sid):
    r = db().execute("SELECT * FROM records WHERE id=? AND module='students'", (sid,)).fetchone()
    if r is None:
        abort(404)
    return dict(json.loads(r["data"]), id=r["id"])


def child_report(kid):
    sid = str(kid["id"])
    mine = lambda m: [r for r in rows_of(m) if str(r.get("sid")) == sid]
    newest = lambda rows: sorted(rows, key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
    groups, order = {}, []
    for r in newest(mine("exams")):
        key = (r.get("exam") or "Exam", (r.get("date") or "")[:7])
        if key not in groups:
            groups[key] = dict(name=key[0], date=r.get("date") or "", rows=[], got=0.0, mx=0.0, absent=0)
            order.append(key)
        g = groups[key]
        absent = r.get("attended") == "Absent"
        row = dict(r, absent=absent, got=num(r.get("marks")), mx=num(r.get("max")))
        row["pct"] = round(row["got"] / row["mx"] * 100) if row["mx"] and not absent else None
        g["rows"].append(row)
        if absent:
            g["absent"] += 1
        else:
            g["got"] += row["got"]
            g["mx"] += row["mx"]
    exams = []
    for k in order:
        g = groups[k]
        g["pct"] = round(g["got"] / g["mx"] * 100) if g["mx"] else None
        g["rows"].sort(key=lambda r: r["id"])
        exams.append(g)
    pcts = [g["pct"] for g in exams if g["pct"] is not None]
    att = sorted(mine("attendance"), key=lambda r: r.get("month") or "", reverse=True)
    wd, pr = sum(num(r.get("working")) for r in att), sum(num(r.get("present")) for r in att)
    for r in att:
        r["pct"] = round(num(r.get("present")) / num(r.get("working")) * 100) if num(r.get("working")) else None
    return dict(exams=exams, avg=round(sum(pcts) / len(pcts)) if pcts else None,
                competitive=newest(mine("competitive")), activities=newest(mine("activities")),
                remarks=newest(mine("remarks")), attendance=att, att_pct=round(pr / wd * 100) if wd else None)


@app.route("/students/<int:sid>")
@login_required
def student_profile(sid):
    kid = _get_student(sid)
    nm = (kid.get("name") or "").strip().lower()
    fees = [f for f in rows_of("fees") if (f.get("student") or "").strip().lower() == nm]
    due, paid = sum(num(f.get("due")) for f in fees), sum(num(f.get("paid")) for f in fees)
    info = [(f["label"], kid.get(f["key"])) for f in fields_of("students")
            if kid.get(f["key"]) and f["key"] not in ("name", "cls", "roll")]
    return render_template("student_profile.html", kid=kid, info=info, fees=fees, due=due, paid=paid,
                           bal=max(due - paid, 0), R=child_report(kid))


DEFAULT_SUBJECTS = ["Telugu", "Hindi", "English", "Mathematics", "Science", "Social Studies"]


@app.route("/students/<int:sid>/marks", methods=["GET", "POST"])
@login_required
def marks_entry(sid):
    kid = _get_student(sid)
    if request.method == "POST":
        f = request.form
        exam, date_, mx = f.get("exam", "").strip()[:60], f.get("date", "").strip()[:10], f.get("max", "100").strip() or "100"
        if not exam:
            flash("Please choose or type the exam name.")
            return redirect(url_for("marks_entry", sid=sid))
        _ensure_exam(exam)
        absent, n = set(f.getlist("absent")), 0
        subjects, marks = f.getlist("subject"), f.getlist("marks")
        for i, sub in enumerate(subjects):
            sub, got = sub.strip()[:60], (marks[i].strip() if i < len(marks) else "")
            is_abs = str(i) in absent
            if not sub or (not is_abs and got == ""):
                continue
            rec = dict(sid=str(sid), student=kid.get("name", ""), cls=kid.get("cls", ""), exam=exam, subject=sub, date=date_,
                       max=mx, marks="" if is_abs else got, attended="Absent" if is_abs else "Attended", remarks="")
            db().execute("INSERT INTO records(module,data) VALUES('exams',?)", (json.dumps(rec),))
            n += 1
        db().commit()
        flash(f"{n} subject mark(s) saved for {kid.get('name', '')}." if n else "Nothing was saved - enter at least one mark.")
        return redirect(url_for("student_profile", sid=sid))
    return render_template("marks_entry.html", kid=kid, subjects=DEFAULT_SUBJECTS, exam_names=_exam_names())


# ---------- audit log, teacher accounts, backups, PIN warning ----------
def audit(action, detail=""):
    try:
        who = session.get("tname") or session.get("user") or session.get("role") or "visitor"
        db().execute("INSERT INTO audit(ts,who,action,detail) VALUES(?,?,?,?)",
                     (datetime.now().isoformat(" ", "seconds"), who, action[:60], str(detail)[:200]))
        db().commit()
    except Exception:
        pass


def weak_pins():
    st = {r["k"]: r["v"] for r in db().execute("SELECT * FROM settings")}
    out = []
    if check_password_hash(st["pin"], "admin123"):
        out.append("the Admin PIN is still admin123")
    if check_password_hash(st["staff_pin"], "staff123"):
        out.append("the shared Staff PIN is still staff123")
    if st.get("parent_default_pin", "parent123") == "parent123":
        out.append("the default parent password is still parent123")
    return out


BACKUP_DIR = os.path.join(BASE, "backups")
_bk = {"d": ""}


@app.before_request
def maybe_backup():
    today = date.today().isoformat()
    if _bk["d"] == today:
        return
    _bk["d"] = today
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"school-{today}.db")
        if not os.path.exists(path):
            src, dst = sqlite3.connect(DB), sqlite3.connect(path)
            src.backup(dst)
            dst.close()
            src.close()
        for f in sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("school-") and x.endswith(".db"))[:-14]:
            os.remove(os.path.join(BACKUP_DIR, f))
        wk, up = date.today().isocalendar(), os.path.join(BASE, "static", "uploads")
        zbase = os.path.join(BACKUP_DIR, f"uploads-{wk[0]}-W{wk[1]:02d}")
        if os.path.isdir(up) and os.listdir(up) and not os.path.exists(zbase + ".zip"):
            shutil.make_archive(zbase, "zip", up)
        for f in sorted(x for x in os.listdir(BACKUP_DIR) if x.startswith("uploads-") and x.endswith(".zip"))[:-4]:
            os.remove(os.path.join(BACKUP_DIR, f))
    except Exception:
        pass


@app.route("/principal/backups")
@admin_only
def backups():
    files = sorted((x for x in os.listdir(BACKUP_DIR) if x.endswith((".db", ".zip"))), reverse=True) if os.path.isdir(BACKUP_DIR) else []
    return render_template("backups.html", files=[(f, os.path.getsize(os.path.join(BACKUP_DIR, f)) // 1024) for f in files])


@app.route("/principal/backups/<name>")
@admin_only
def backup_download(name):
    if not re.fullmatch(r"school-\d{4}-\d{2}-\d{2}\.db|before-promotion-\d{8}-\d{4}\.db|uploads-\d{4}-W\d{2}\.zip", name):
        abort(404)
    return send_from_directory(BACKUP_DIR, name, as_attachment=True)


@app.route("/principal/audit")
@admin_only
def audit_log():
    rows = db().execute("SELECT * FROM audit ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("audit.html", rows=rows)


def _pin_taken(pin, skip_id=None):
    st = {r["k"]: r["v"] for r in db().execute("SELECT * FROM settings")}
    if check_password_hash(st["pin"], pin) or check_password_hash(st["staff_pin"], pin):
        return True
    return any(check_password_hash(u["pw"], pin) for u in db().execute("SELECT * FROM staff_users") if u["id"] != skip_id)


@app.route("/principal/staff", methods=["GET", "POST"])
@admin_only
def staff_users():
    if request.method == "POST":
        name, pin = request.form.get("name", "").strip()[:60], request.form.get("pin", "").strip()
        if not name or len(pin) < 4:
            flash("Enter the teacher's name and a PIN of at least 4 characters.")
        elif _pin_taken(pin):
            flash("That PIN is already used by someone else. Please choose a different PIN.")
        else:
            db().execute("INSERT INTO staff_users(name,pw,active) VALUES(?,?,1)", (name, generate_password_hash(pin)))
            db().commit()
            audit("Teacher login created", name)
            flash(f"Login created for {name}. They sign in with their own PIN at Staff Login.")
        return redirect(url_for("staff_users"))
    return render_template("staff_users.html", users=db().execute("SELECT * FROM staff_users ORDER BY id DESC").fetchall())


@app.post("/principal/staff/<int:uid>")
@admin_only
def staff_user_update(uid):
    u = db().execute("SELECT * FROM staff_users WHERE id=?", (uid,)).fetchone()
    if u is None:
        abort(404)
    act = request.form.get("act")
    if act == "delete":
        db().execute("DELETE FROM staff_users WHERE id=?", (uid,))
        flash("Teacher login deleted.")
    elif act == "toggle":
        db().execute("UPDATE staff_users SET active=? WHERE id=?", (0 if u["active"] else 1, uid))
    elif act == "pin":
        pin = request.form.get("pin", "").strip()
        if len(pin) < 4 or _pin_taken(pin, uid):
            flash("Choose a PIN of at least 4 characters that nobody else uses.")
        else:
            db().execute("UPDATE staff_users SET pw=? WHERE id=?", (generate_password_hash(pin), uid))
            flash("PIN changed.")
    db().commit()
    audit("Teacher login " + (act or ""), u["name"])
    return redirect(url_for("staff_users"))


# ---------- report cards, class-wise marks, daily attendance ----------
def _class_students(cls):
    return sorted((r for r in rows_of("students") if r.get("cls") == cls),
                  key=lambda r: (int(r["roll"]) if str(r.get("roll", "")).isdigit() else 9999, (r.get("name") or "").lower()))


def _exam_rank(kid, name, month, pct):
    if pct is None or not kid.get("cls"):
        return None, None
    tot = {}
    for r in rows_of("exams"):
        if r.get("cls") == kid.get("cls") and r.get("exam") == name and (r.get("date") or "")[:7] == month and r.get("attended") != "Absent":
            t = tot.setdefault(str(r.get("sid")), [0.0, 0.0])
            t[0] += num(r.get("marks"))
            t[1] += num(r.get("max"))
    pcts = [round(a / b * 100, 2) for a, b in tot.values() if b]
    pct = round(pct, 2)
    return 1 + sum(1 for x in pcts if x > pct), len(pcts)


def daily_months(sid):
    out = {}
    for r in db().execute("SELECT d, status FROM att_daily WHERE sid=?", (sid,)):
        m = out.setdefault(r["d"][:7], [0, 0])
        m[1] += 1
        if r["status"] == "P":
            m[0] += 1
    return out


_old_child_report = child_report


def child_report(kid):
    R = _old_child_report(kid)
    for g in R["exams"]:
        g["rank"], g["of"] = _exam_rank(kid, g["name"], (g["date"] or "")[:7], (g["got"] / g["mx"] * 100) if g["mx"] else None)
    manual = {r.get("month"): r for r in R["attendance"]}
    for mth, (pres, work) in daily_months(kid["id"]).items():
        if mth not in manual:
            R["attendance"].append(dict(id=None, month=mth, working=work, present=pres, pct=round(pres / work * 100) if work else None, auto=True))
    R["attendance"].sort(key=lambda r: r.get("month") or "", reverse=True)
    wd, pr = sum(num(r.get("working")) for r in R["attendance"]), sum(num(r.get("present")) for r in R["attendance"])
    R["att_pct"] = round(pr / wd * 100) if wd else None
    R["trend"] = [(g["name"], g["pct"]) for g in reversed(R["exams"]) if g["pct"] is not None]
    mine_img = [im for im in rows_of("exam_images")
                if str(im.get("sid")) == str(kid["id"]) or (not im.get("sid") and im.get("cls") in ("All classes", kid.get("cls")))]
    used = set()
    for g in R["exams"]:
        g["images"] = [im for im in mine_img if im.get("exam") == g["name"] and (not im.get("month") or im["month"] == (g["date"] or "")[:7])]
        used.update(im["id"] for im in g["images"])
    R["exam_extra"] = [im for im in mine_img if im["id"] not in used]
    return R


def _report_card_view(kid, back):
    R = child_report(kid)
    ex, mo = request.args.get("exam"), request.args.get("m")
    if ex:
        R = dict(R, exams=[g for g in R["exams"] if g["name"] == ex and (g["date"] or "")[:7] == (mo or "")])
    return render_template("report_card.html", kid=kid, R=R, back=back, only=bool(ex))


@app.route("/students/<int:sid>/report")
@login_required
def report_card(sid):
    return _report_card_view(_get_student(sid), url_for("student_profile", sid=sid))


@app.route("/marks/class", methods=["GET", "POST"])
@login_required
def marks_class():
    q = request.values
    cls, exam, subject = q.get("cls", ""), q.get("exam", "").strip(), q.get("subject", "").strip()
    date_, mx = q.get("date", date.today().isoformat()), q.get("max", "100") or "100"
    studs = _class_students(cls) if cls else []
    existing = {}
    if cls and exam and subject:
        for r in rows_of("exams"):
            if r.get("exam") == exam and r.get("subject") == subject and (r.get("date") or "")[:7] == date_[:7]:
                existing[str(r.get("sid"))] = r
    if request.method == "POST" and studs and exam and subject:
        _ensure_exam(exam)
        absent, n = set(request.form.getlist("absent")), 0
        for st in studs:
            sid = str(st["id"])
            got, is_abs = request.form.get("m_" + sid, "").strip(), sid in absent
            if got == "" and not is_abs:
                continue
            rec = dict(sid=sid, student=st.get("name", ""), cls=cls, exam=exam, subject=subject, date=date_, max=mx,
                       marks="" if is_abs else got, attended="Absent" if is_abs else "Attended", remarks=(existing.get(sid) or {}).get("remarks", ""))
            if sid in existing:
                db().execute("UPDATE records SET data=? WHERE id=?", (json.dumps(rec), existing[sid]["id"]))
            else:
                db().execute("INSERT INTO records(module,data) VALUES('exams',?)", (json.dumps(rec),))
            n += 1
        db().commit()
        audit("Class marks saved", f"Class {cls} {exam} {subject}: {n} students")
        flash(f"Marks saved for {n} student(s) - Class {cls}, {exam}, {subject}.")
        return redirect(url_for("marks_class", cls=cls, exam=exam, subject=subject, date=date_, max=mx))
    return render_template("marks_class.html", cls=cls, exam=exam, subject=subject, date=date_, max=mx, studs=studs,
                           existing=existing, classes=CLASSES, subjects=DEFAULT_SUBJECTS, exam_names=_exam_names())


@app.route("/attendance/daily", methods=["GET", "POST"])
@login_required
def att_daily():
    cls, day = request.values.get("cls", ""), request.values.get("date", date.today().isoformat())
    studs = _class_students(cls) if cls else []
    if request.method == "POST" and studs:
        for st in studs:
            status = request.form.get("s_" + str(st["id"]), "P")
            db().execute("INSERT OR REPLACE INTO att_daily(sid,d,status) VALUES(?,?,?)", (st["id"], day, status if status in ("P", "A", "L") else "P"))
        db().commit()
        audit("Daily attendance", f"Class {cls} {day}")
        flash(f"Attendance saved for Class {cls} on {day}.")
        return redirect(url_for("att_daily", cls=cls, date=day))
    cur = {r["sid"]: r["status"] for r in db().execute("SELECT sid,status FROM att_daily WHERE d=?", (day,))}
    return render_template("att_daily.html", cls=cls, day=day, studs=studs, cur=cur, classes=CLASSES)


# ---------- fee receipts, pending fees and WhatsApp reminders ----------
def _fee_student(f):
    nm = (f.get("student") or "").strip().lower()
    return next((s for s in rows_of("students") if (s.get("name") or "").strip().lower() == nm), {})


def _receipt_view(rid, back):
    r = db().execute("SELECT * FROM records WHERE id=? AND module='fees'", (rid,)).fetchone()
    if r is None:
        abort(404)
    f = dict(json.loads(r["data"]), id=r["id"])
    nm = (f.get("student") or "").strip().lower()
    all_fees = [x for x in rows_of("fees") if (x.get("student") or "").strip().lower() == nm]
    due, paid = sum(num(x.get("due")) for x in all_fees), sum(num(x.get("paid")) for x in all_fees)
    return render_template("receipt.html", f=f, stu=_fee_student(f), tot_bal=max(due - paid, 0), back=back)


@app.route("/fees/<int:rid>/receipt")
@login_required
def fee_receipt(rid):
    return _receipt_view(rid, url_for("listing", m="fees"))


@app.route("/fees/pending")
@login_required
def pending_fees():
    studs = {(s.get("name") or "").strip().lower(): s for s in rows_of("students")}
    agg = {}
    for f in rows_of("fees"):
        k = (f.get("student") or "").strip().lower()
        a = agg.setdefault(k, dict(name=f.get("student"), due=0.0, paid=0.0))
        a["due"] += num(f.get("due"))
        a["paid"] += num(f.get("paid"))
    rows = []
    for k, a in agg.items():
        bal = a["due"] - a["paid"]
        if bal > 0:
            s = studs.get(k, {})
            ph = norm_phone(s.get("phone", ""))
            msg = (f"Dear Parent, a reminder from {SCHOOL}: the pending fee for {a['name']}"
                   f"{' (Class ' + s['cls'] + ')' if s.get('cls') else ''} is Rs. {bal:,.0f}. Kindly pay it at the earliest. Thank you.")
            rows.append(dict(name=a["name"], cls=s.get("cls", ""), phone=ph, bal=bal, msg=msg,
                             wa=("https://wa.me/91" + ph + "?text=" + quote(msg)) if len(ph) == 10 else ""))
    rows.sort(key=lambda r: -r["bal"])
    return render_template("pending_fees.html", rows=rows, total=sum(r["bal"] for r in rows))


# ---------- ID cards and transfer certificate ----------
@app.route("/idcards")
@login_required
def idcards():
    cls, sid = request.args.get("cls", ""), request.args.get("sid", type=int)
    studs = [_get_student(sid)] if sid else (_class_students(cls) if cls else [])
    return render_template("idcards.html", studs=studs, cls=cls, classes=CLASSES, year=date.today().year)


@app.route("/students/<int:sid>/tc")
@login_required
def tc_page(sid):
    return render_template("tc.html", kid=_get_student(sid))


# ---------- import students from CSV / Excel ----------
IMPORT_COLS = {"name": "name", "student name": "name", "class": "cls", "cls": "cls", "roll": "roll", "roll no": "roll", "dob": "dob",
               "date of birth": "dob", "gender": "gender", "parent": "parent", "parent name": "parent", "guardian": "parent",
               "phone": "phone", "mobile": "phone", "mobile number": "phone", "address": "addr", "section": "section", "sec": "section"}


def _read_table(f):
    name = (f.filename or "").lower()
    raw = f.read()
    if name.endswith(".xlsx"):
        try:
            import openpyxl
        except ImportError:
            return None, "Excel files need the 'openpyxl' package (pip install openpyxl). Or save the sheet as CSV and upload that."
        ws = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True).active
        rows = [[("" if c is None else str(c)).strip() for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    return rows, ""


@app.route("/import/students", methods=["GET", "POST"])
@login_required
def import_students():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Please choose a CSV or Excel file.")
            return redirect(url_for("import_students"))
        rows, err = _read_table(f)
        if err:
            flash(err)
            return redirect(url_for("import_students"))
        if not rows:
            flash("The file is empty.")
            return redirect(url_for("import_students"))
        head = [IMPORT_COLS.get(h.strip().lower()) for h in rows[0]]
        if "name" not in head:
            flash("The first row must have column names, including 'name'. Download the template to see the format.")
            return redirect(url_for("import_students"))
        have = {((s.get("name") or "").strip().lower(), s.get("cls", ""), str(s.get("roll", ""))) for s in rows_of("students")}
        added = skipped = logins = 0
        canon = {c.upper(): c for c in CLASSES}
        for r in rows[1:]:
            d = {k: (r[i].strip() if i < len(r) else "") for i, k in enumerate(head) if k}
            if not d.get("name"):
                continue
            d["cls"] = canon.get(re.sub(r"(?i)class\s*", "", d.get("cls", "")).strip().upper(), d.get("cls", ""))
            if d.get("gender"):
                d["gender"] = {"m": "Male", "male": "Male", "f": "Female", "female": "Female"}.get(d["gender"].lower(), d["gender"])
            key = (d["name"].lower(), d.get("cls", ""), str(d.get("roll", "")))
            if key in have:
                skipped += 1
                continue
            have.add(key)
            sid = db().execute("INSERT INTO records(module,data) VALUES('students',?)", (json.dumps(d),)).lastrowid
            db().commit()
            added += 1
            if auto_parent_login(sid, d).startswith(("Parent login created", "This mobile")):
                logins += 1
        audit("Imported students", f"{added} added, {skipped} skipped")
        flash(f"Import finished: {added} student(s) added, {skipped} skipped (already present), {logins} linked to a parent login.")
        return redirect(url_for("listing", m="students"))
    return render_template("import_students.html")


@app.route("/import/students/template.csv")
@login_required
def import_template():
    return Response("name,class,roll,dob,gender,parent,mobile,address\nAarav Kumar,5,12,2015-04-10,Male,Suresh Kumar,9876500001,Main Road\n",
                    mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=students-template.csv"})


# ---------- parent extras: report card, receipts, feedback ----------
def _parent_kids():
    p = db().execute("SELECT * FROM parents WHERE id=?", (session["parent"],)).fetchone()
    return p, _students_by_ids(json.loads(p["students"] or "[]"))


@app.route("/parent/report/<int:sid>")
@parent_required
def parent_report(sid):
    _, kids = _parent_kids()
    kid = next((k for k in kids if k["id"] == sid), None)
    if kid is None:
        abort(404)
    return _report_card_view(kid, url_for("parent_home"))


@app.route("/parent/receipt/<int:rid>")
@parent_required
def parent_receipt(rid):
    _, kids = _parent_kids()
    r = db().execute("SELECT * FROM records WHERE id=? AND module='fees'", (rid,)).fetchone()
    if r is None or (json.loads(r["data"]).get("student") or "").strip().lower() not in {(k.get("name") or "").strip().lower() for k in kids}:
        abort(404)
    return _receipt_view(rid, url_for("parent_home"))


@app.post("/parent/feedback")
@parent_required
def parent_feedback():
    p, kids = _parent_kids()
    msg, sid = request.form.get("message", "").strip()[:1000], request.form.get("sid", type=int)
    kid = next((k for k in kids if k["id"] == sid), None)
    if not msg or kid is None:
        flash("Please type your message.")
    else:
        rec = dict(sid=str(kid["id"]), student=kid.get("name", ""), cls=kid.get("cls", ""), date=date.today().isoformat(), message=msg, status="New", parent=p["name"] or p["username"])
        db().execute("INSERT INTO records(module,data) VALUES('feedback',?)", (json.dumps(rec),))
        db().commit()
        flash("Thank you! Your message was sent to the school.")
    return redirect(url_for("parent_home") + "#feedback")


# ---------- installable app (PWA) ----------
@app.route("/manifest.webmanifest")
def manifest():
    m = {"name": SCHOOL, "short_name": "RK Little Buds", "start_url": "/", "display": "standalone", "background_color": "#ffffff",
         "theme_color": "#7b2d8e", "icons": [{"src": url_for("static", filename="icon-192.png"), "sizes": "192x192", "type": "image/png"},
                                              {"src": url_for("static", filename="logo.png"), "sizes": "512x512", "type": "image/png"}]}
    return Response(json.dumps(m), mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    js = """const C='rk-v2';self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin)return;
if(u.pathname.startsWith('/static/')||u.pathname==='/'){e.respondWith(fetch(e.request).then(n=>{if(n.ok){const k=n.clone();caches.open(C).then(c=>c.put(e.request,k))}return n}).catch(()=>caches.match(e.request)))}});"""
    return Response(js, mimetype="application/javascript", headers={"Service-Worker-Allowed": "/"})


# ---------- exam names (add / rename / reorder) and exam images ----------
DEFAULT_EXAMS = ["Weekly Test", "Unit Test 1", "Unit Test 2", "Quarterly", "Half-Yearly", "Pre-Final", "Annual"]


def _exam_names():
    return [r["name"] for r in db().execute("SELECT name FROM exam_names ORDER BY sort, id")]


def _stu_groups():
    g = {}
    for s in _student_options():
        g.setdefault(s.get("cls") or "-", []).append(s)
    order = {c: i for i, c in enumerate(CLASSES)}
    return sorted(g.items(), key=lambda kv: order.get(kv[0], 99))


def _ensure_exam(name):
    name = (name or "").strip()[:60]
    if name and not db().execute("SELECT 1 FROM exam_names WHERE name=?", (name,)).fetchone():
        nxt = db().execute("SELECT COALESCE(MAX(sort),0)+1 FROM exam_names").fetchone()[0]
        db().execute("INSERT INTO exam_names(name,sort) VALUES(?,?)", (name, nxt))
        db().commit()


@app.route("/exams/names", methods=["GET", "POST"])
@login_required
def exam_names():
    if request.method == "POST":
        act, name = request.form.get("act"), request.form.get("name", "").strip()[:60]
        eid = request.form.get("id", type=int)
        row = db().execute("SELECT * FROM exam_names WHERE id=?", (eid,)).fetchone() if eid else None
        if act == "add":
            if not name:
                flash("Please type the exam name.")
            elif db().execute("SELECT 1 FROM exam_names WHERE name=?", (name,)).fetchone():
                flash("That exam name already exists.")
            else:
                _ensure_exam(name)
                audit("Exam name added", name)
                flash(f"Exam “{name}” added. It now appears in all marks forms.")
        elif act == "rename" and row:
            if not name:
                flash("Please type the new name.")
            elif db().execute("SELECT 1 FROM exam_names WHERE name=? AND id<>?", (name, eid)).fetchone():
                flash("Another exam already has that name.")
            elif name != row["name"]:
                n = 0
                for r in db().execute("SELECT id,data FROM records WHERE module IN ('exams','exam_images')").fetchall():
                    d = json.loads(r["data"])
                    if d.get("exam") == row["name"]:
                        d["exam"] = name
                        db().execute("UPDATE records SET data=? WHERE id=?", (json.dumps(d), r["id"]))
                        n += 1
                db().execute("UPDATE exam_names SET name=? WHERE id=?", (name, eid))
                db().commit()
                audit("Exam renamed", f"{row['name']} -> {name} ({n} records)")
                flash(f"Renamed to “{name}”. {n} saved mark/image record(s) were updated too.")
        elif act in ("up", "down") and row:
            ids = [r["id"] for r in db().execute("SELECT id FROM exam_names ORDER BY sort, id")]
            i = ids.index(eid)
            j = i - 1 if act == "up" else i + 1
            if 0 <= j < len(ids):
                ids[i], ids[j] = ids[j], ids[i]
                for pos, x in enumerate(ids):
                    db().execute("UPDATE exam_names SET sort=? WHERE id=?", (pos, x))
                db().commit()
        elif act == "delete" and row:
            if session.get("role") != "admin":
                flash("Only the Admin can delete an exam name.")
            else:
                db().execute("DELETE FROM exam_names WHERE id=?", (eid,))
                db().commit()
                audit("Exam name deleted", row["name"])
                flash(f"“{row['name']}” removed from the list. Marks already saved keep their exam name.")
        return redirect(url_for("exam_names"))
    counts = Counter(r.get("exam") for r in rows_of("exams"))
    imgs = Counter(r.get("exam") for r in rows_of("exam_images"))
    rows = [dict(r, marks=counts.get(r["name"], 0), images=imgs.get(r["name"], 0))
            for r in db().execute("SELECT * FROM exam_names ORDER BY sort, id")]
    return render_template("exam_names.html", rows=rows)


@app.route("/exams/images", methods=["GET", "POST"])
@login_required
def exam_images():
    if request.method == "POST":
        f = request.form
        exam, cap, month = f.get("exam", "").strip()[:60], f.get("caption", "").strip()[:120], f.get("month", "").strip()[:7]
        files = [x for x in request.files.getlist("images") if _is_img(x)]
        sid, scope = f.get("sid", type=int), f.get("scope", "class")
        stu = _get_student(sid) if scope == "student" and sid else None
        if not exam or not files or (scope == "student" and stu is None):
            flash("Choose the exam, who it is for, and at least one image (PNG, JPG or WEBP).")
            return redirect(url_for("exam_images"))
        _ensure_exam(exam)
        cls = stu.get("cls", "") if stu else (f.get("cls") or "All classes")
        for x in files:
            rec = dict(exam=exam, cls=cls, sid=str(stu["id"]) if stu else "", student=stu.get("name", "") if stu else "",
                       caption=cap, month=month, date=date.today().isoformat(), image=_save_img(x, "exams"))
            db().execute("INSERT INTO records(module,data) VALUES('exam_images',?)", (json.dumps(rec),))
        db().commit()
        audit("Exam images added", f"{exam}: {len(files)} image(s)")
        flash(f"{len(files)} image(s) uploaded for {exam}.")
        return redirect(url_for("exam_images", exam=exam))
    fx, fc = request.args.get("exam", ""), request.args.get("cls", "")
    items = [r for r in rows_of("exam_images") if (not fx or r.get("exam") == fx) and (not fc or r.get("cls") in (fc, "All classes"))]
    groups = {}
    for r in items:
        groups.setdefault(r.get("exam") or "Exam", []).append(r)
    order = {n: i for i, n in enumerate(_exam_names())}
    return render_template("exam_images.html", names=_exam_names(), classes=CLASSES, stu_groups=_stu_groups(),
                           groups=sorted(groups.items(), key=lambda kv: order.get(kv[0], 999)),
                           fx=fx, fc=fc, prefill=request.args.get("sid", type=int))


@app.post("/exams/images/<int:rid>/delete")
@login_required
def exam_image_delete(rid):
    r = db().execute("SELECT * FROM records WHERE id=? AND module='exam_images'", (rid,)).fetchone()
    if r is None:
        abort(404)
    d = json.loads(r["data"])
    _rm(d.get("image"))
    db().execute("DELETE FROM records WHERE id=?", (rid,))
    db().commit()
    audit("Exam image deleted", d.get("exam", ""))
    flash("Image deleted.")
    return redirect(request.referrer or url_for("exam_images"))


# ---------- data analysis reports (see reports.py) ----------
import reports as RP


def _setting(k, default=""):
    row = db().execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return row["v"] if row else default


def thresholds():
    def f(k, d):
        try:
            return float(_setting(k, str(d)))
        except ValueError:
            return float(d)
    return dict(pass_mark=f("pass_mark", 35), att_alert=f("att_alert", 75), drop_alert=f("drop_alert", 10))


def current_ay():
    return RP.ay_of(date.today().isoformat())


def _ay():
    ay = request.args.get("year")
    return current_ay() if ay is None else ay      # "" = all years


def all_years():
    ys = {current_ay()}
    for m in ("exams", "fees", "admissions", "competitive"):
        ys.update(RP.ay_of(r.get("date")) for r in rows_of(m))
    ys.update(RP.ay_of(r["d"]) for r in db().execute("SELECT DISTINCT d FROM att_daily"))
    return sorted((y for y in ys if y), reverse=True)


def active_students():
    return [s for s in rows_of("students") if s.get("cls") in CLASSES]


def att_months():
    am = {}
    for r in rows_of("attendance"):
        if r.get("month"):
            am.setdefault(str(r.get("sid")), {})[r["month"]] = [num(r.get("present")), num(r.get("working"))]
    for r in db().execute("SELECT sid, substr(d,1,7) m, SUM(status='P') p, COUNT(*) w FROM att_daily GROUP BY sid, m"):
        am.setdefault(str(r["sid"]), {}).setdefault(r["m"], [r["p"], r["w"]])
    return am


def _xlsx(name, sheets):
    try:
        import openpyxl
    except ImportError:
        flash("Excel download needs the 'openpyxl' package (pip install openpyxl).")
        return redirect(request.referrer or url_for("reports_hub"))
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, (head, rows) in sheets.items():
        ws = wb.create_sheet(title[:30])
        ws.append(head)
        for r in rows:
            ws.append(list(r))
        for i, h in enumerate(head, 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = max(12, min(40, len(str(h)) + 6))
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={name}.xlsx"})


def _days(d):
    try:
        return (date.today() - date.fromisoformat(d)).days
    except (TypeError, ValueError):
        return ""


def _ctx(**kw):
    return dict(ay=_ay(), years=all_years(), th=thresholds(), **kw)


@app.route("/reports")
@login_required
def reports_hub():
    ay, th, studs = _ay(), thresholds(), active_students()
    exams, am = rows_of("exams"), att_months()
    att = RP.attention(studs, exams, am, ay, th["pass_mark"], th["att_alert"], th["drop_alert"])
    fa = RP.fee_analysis(rows_of("fees"), studs, ay)
    ad = RP.admissions_analysis(rows_of("admissions"), ay)
    ps = [RP.pct(num(r.get("marks")), num(r.get("max"))) for r in exams if RP.in_year(r.get("date"), ay) and r.get("attended") != "Absent" and num(r.get("max"))]
    pr = sum(v[0] for s in am.values() for m, v in s.items() if RP.in_year(m + "-01", ay))
    wk = sum(v[1] for s in am.values() for m, v in s.items() if RP.in_year(m + "-01", ay))
    return render_template("reports_hub.html", **_ctx(n_att=len(att), fee=fa, adm=ad, avg=round(sum(ps) / len(ps), 1) if ps else None,
                                                      att_pct=round(pr / wk * 100) if wk else None, n_students=len(studs)))


@app.post("/reports/settings")
@admin_only
def reports_settings():
    for k in ("pass_mark", "att_alert", "drop_alert"):
        v = request.form.get(k, "").strip()
        try:
            float(v)
        except ValueError:
            continue
        db().execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
    db().commit()
    audit("Report settings changed")
    flash("Report settings saved.")
    return redirect(url_for("reports_hub"))


def _class_report_data():
    cls, exam, ay = request.args.get("cls", ""), request.args.get("exam", ""), _ay()
    data = RP.class_exam(rows_of("students"), rows_of("exams"), cls, exam, ay, thresholds()["pass_mark"]) if cls and exam else None
    return cls, exam, ay, data


@app.route("/reports/class")
@login_required
def rep_class():
    cls, exam, ay, data = _class_report_data()
    return render_template("rep_class.html", **_ctx(cls=cls, exam=exam, data=data, classes=CLASSES, names=_exam_names(), heat=RP.heat,
                                                    subj_bars=[(s["name"], s["avg"] or 0) for s in data["subj_stats"]] if data else []))


@app.route("/reports/class.xlsx")
@login_required
def rep_class_xlsx():
    cls, exam, ay, d = _class_report_data()
    if not d:
        return redirect(url_for("rep_class"))
    head = ["Rank", "Roll", "Student"] + d["subjects"] + ["Total", "Max", "Percentage", "Result"]
    rows = [[r["rank"], r["roll"], r["name"]] + [("Abs" if r["subj"].get(s, {}).get("absent") else r["subj"].get(s, {}).get("got", "")) for s in d["subjects"]]
            + [r["got"], r["mx"], r["pct"], "Pass" if r["passed"] else "Needs help: " + ", ".join(r["fails"])] for r in d["rows"]]
    sub = [[s["name"], s["n"], s["avg"], s["hi"], s["lo"], s["pass_pct"]] for s in d["subj_stats"]]
    return _xlsx(f"class-{cls}-{exam}", {"Students": (head, rows), "Subjects": (["Subject", "Students", "Average %", "Highest %", "Lowest %", "Pass %"], sub)})


def _attention_data():
    th, cls = thresholds(), request.args.get("cls", "")
    rows = RP.attention(active_students(), rows_of("exams"), att_months(), _ay(), th["pass_mark"], th["att_alert"], th["drop_alert"])
    return [r for r in rows if not cls or r["cls"] == cls], cls


@app.route("/reports/attention")
@login_required
def rep_attention():
    rows, cls = _attention_data()
    return render_template("rep_attention.html", **_ctx(rows=rows, cls=cls, classes=CLASSES))


@app.route("/reports/attention.xlsx")
@login_required
def rep_attention_xlsx():
    rows, _ = _attention_data()
    return _xlsx("needs-attention", {"Needs attention": (["Class", "Roll", "Student", "Mobile", "Last exam %", "Attendance %", "Reasons"],
                                                         [[r["cls"], r["roll"], r["name"], r["phone"], r["last_pct"], r["att"], "; ".join(r["why"])] for r in rows])})


@app.route("/reports/subjects")
@login_required
def rep_subjects():
    ay = _ay()
    m = RP.subject_matrix(rows_of("exams"), ay, CLASSES)
    seen = {e for t in m["trend"].values() for e in t}
    return render_template("rep_subjects.html", **_ctx(m=m, trend_exams=[e for e in _exam_names() if e in seen] + sorted(seen - set(_exam_names())),
                                                       overall_bars=[(s, a or 0) for s, a, n in m["overall"]], heat=RP.heat))


def _att_report():
    ay, th = _ay(), thresholds()
    studs, am, exams = active_students(), att_months(), rows_of("exams")
    months, rows = RP.monthly_by_class(studs, am, ay, CLASSES)
    marks = {str(sid): (g[-1][2] if g else None) for sid, g in RP.exam_groups(exams, ay).items()}
    low = []
    for s in studs:
        p = RP.att_overall(am, str(s["id"]), ay)
        if p is not None and p < th["att_alert"]:
            low.append(dict(name=s.get("name"), cls=s.get("cls"), roll=s.get("roll"), att=p, marks=marks.get(str(s["id"]))))
    low.sort(key=lambda r: r["att"])
    return months, rows, low


@app.route("/reports/attendance")
@login_required
def rep_attendance():
    months, rows, low = _att_report()
    return render_template("rep_attendance.html", **_ctx(months=months, rows=rows, low=low, heat=RP.heat))


@app.route("/reports/attendance.xlsx")
@login_required
def rep_attendance_xlsx():
    months, rows, low = _att_report()
    return _xlsx("attendance", {"By class": (["Class"] + months + ["Overall %"], [[r["cls"]] + [r["cells"].get(m) for m in months] + [r["overall"]] for r in rows]),
                                "Low attendance": (["Class", "Roll", "Student", "Attendance %", "Last exam %"], [[r["cls"], r["roll"], r["name"], r["att"], r["marks"]] for r in low])})


@app.route("/reports/fees")
@login_required
def rep_fees():
    fa = RP.fee_analysis(rows_of("fees"), rows_of("students"), _ay())
    return render_template("rep_fees.html", **_ctx(fa=fa, days=_days, class_rows=sorted(((c, v[1], v[0] - v[1]) for c, v in fa["by_class"].items() if c in CLASSES), key=lambda x: CLASSES.index(x[0]))))


@app.route("/reports/fees.xlsx")
@login_required
def rep_fees_xlsx():
    fa = RP.fee_analysis(rows_of("fees"), rows_of("students"), _ay())
    return _xlsx("fees", {"By class": (["Class", "Due", "Collected", "Pending"], [[c, v[0], v[1], v[0] - v[1]] for c, v in fa["by_class"].items()]),
                          "By month": (["Month", "Collected"], fa["by_month"]),
                          "Pending families": (["Student", "Class", "Pending", "Oldest record"], [[p["name"], p["cls"], p["bal"], p["oldest"]] for p in fa["pending"]])})


@app.route("/reports/admissions")
@login_required
def rep_adm():
    return render_template("rep_adm.html", **_ctx(a=RP.admissions_analysis(rows_of("admissions"), _ay())))


@app.route("/reports/competitive")
@login_required
def rep_comp():
    return render_template("rep_comp.html", **_ctx(c=RP.competitive_analysis(rows_of("competitive"), _ay())))


@app.route("/reports/years")
@login_required
def rep_years():
    exams, fees, adm, am = rows_of("exams"), rows_of("fees"), rows_of("admissions"), att_months()
    rows = []
    for y in all_years():
        ps = [RP.pct(num(r.get("marks")), num(r.get("max"))) for r in exams if RP.in_year(r.get("date"), y) and r.get("attended") != "Absent" and num(r.get("max"))]
        pr = sum(v[0] for s in am.values() for m, v in s.items() if RP.in_year(m + "-01", y))
        wk = sum(v[1] for s in am.values() for m, v in s.items() if RP.in_year(m + "-01", y))
        a = RP.admissions_analysis(adm, y)
        rows.append(dict(year=y, avg=round(sum(ps) / len(ps), 1) if ps else None, att=round(pr / wk * 100) if wk else None,
                         fees=sum(num(f.get("paid")) for f in fees if RP.in_year(f.get("date"), y)), adm=a["n"], admitted=a["status"].get("Admitted", 0)))
    site = get_site()
    ssc = [list(r) for r in site.get("results_history", [])]
    cur = site.get("results") or {}
    if cur.get("total"):
        ssc.append(["Latest", cur.get("total"), cur.get("passed"), cur.get("a500"), cur.get("a400"), cur.get("b400")])
    strength = Counter(s.get("cls") for s in active_students())
    return render_template("rep_years.html", **_ctx(rows=rows, ssc=ssc, strength=[(c, strength[c]) for c in CLASSES if strength[c]]))


def dash_analytics():
    ay, th, studs = current_ay(), thresholds(), active_students()
    att = RP.attention(studs, rows_of("exams"), att_months(), ay, th["pass_mark"], th["att_alert"], th["drop_alert"])
    fa = RP.fee_analysis(rows_of("fees"), studs, ay)
    ad = RP.admissions_analysis(rows_of("admissions"), ay)
    done = {r["sid"] for r in db().execute("SELECT sid FROM att_daily WHERE d=?", (date.today().isoformat(),))}
    unmarked = [c for c in CLASSES if any(s.get("cls") == c for s in studs) and not any(s["id"] in done for s in studs if s.get("cls") == c)] if date.today().weekday() != 6 else []
    return dict(n_att=len(att), top_att=att[:5], fee_class=sorted(((c, v[1], v[0] - v[1]) for c, v in fa["by_class"].items() if c in CLASSES), key=lambda x: CLASSES.index(x[0])),
                pending_n=len(fa["pending"]), pending_amt=sum(p["bal"] for p in fa["pending"]), adm=ad, unmarked=unmarked, ay=ay)


# ---------- global search ----------
@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip().lower()
    res = {}
    if len(q) >= 2:
        def hit(r, keys):
            return any(q in str(r.get(k, "")).lower() for k in keys)
        res["Students"] = [r for r in rows_of("students") if hit(r, ("name", "phone", "parent", "roll", "addr"))][:30]
        res["Teachers"] = [r for r in rows_of("teachers") if hit(r, ("name", "subject", "phone", "classes"))][:30]
        res["Admissions"] = [r for r in rows_of("admissions") if hit(r, ("name", "parent", "phone"))][:30]
        res["Fee records"] = [r for r in rows_of("fees") if hit(r, ("student",))][:30]
        if session.get("role") == "admin":
            res["Parent logins"] = [dict(p) for p in db().execute("SELECT * FROM parents") if q in (p["username"] or "").lower() or q in (p["name"] or "").lower()][:30]
    return render_template("search.html", q=request.args.get("q", ""), res={k: v for k, v in res.items() if v}, short=len(q) < 2)


# ---------- year-end class promotion ----------
NEXT_CLASS = dict(zip(CLASSES, CLASSES[1:] + ["Alumni"]))


@app.route("/principal/promote", methods=["GET", "POST"])
@admin_only
def promote():
    ay, done = current_ay(), None
    done = _setting("last_promotion") == current_ay()
    counts = Counter(s.get("cls") for s in rows_of("students"))
    if request.method == "POST":
        if request.form.get("confirm", "").strip().upper() != "PROMOTE":
            flash("Type PROMOTE in the box to confirm.")
        elif done and not request.form.get("again"):
            flash("Classes were already promoted for this academic year. Tick the extra box only if you really want to do it again.")
        else:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            bp = os.path.join(BACKUP_DIR, f"before-promotion-{datetime.now().strftime('%Y%m%d-%H%M')}.db")
            src, dst = sqlite3.connect(DB), sqlite3.connect(bp)
            src.backup(dst)
            dst.close()
            src.close()
            n = 0
            for r in db().execute("SELECT id,data FROM records WHERE module='students'").fetchall():
                d = json.loads(r["data"])
                if d.get("cls") in NEXT_CLASS:
                    d["history"] = (d.get("history") or []) + [{"year": ay, "cls": d["cls"]}]
                    d["cls"] = NEXT_CLASS[d["cls"]]
                    db().execute("UPDATE records SET data=? WHERE id=?", (json.dumps(d), r["id"]))
                    n += 1
            db().execute("INSERT OR REPLACE INTO settings VALUES('last_promotion',?)", (ay,))
            db().commit()
            audit("Classes promoted", f"{n} students, {ay}")
            flash(f"Done: {n} student(s) moved up one class. Class 10 students are now 'Alumni'. A backup was saved first.")
            return redirect(url_for("promote"))
    return render_template("promote.html", ay=ay, done=done, counts=[(c, counts.get(c, 0), NEXT_CLASS[c]) for c in CLASSES], alumni=counts.get("Alumni", 0))


# ---------- parents: notice acknowledgement ----------
@app.post("/parent/notice/<int:nid>/read")
@parent_required
def parent_notice_read(nid):
    db().execute("INSERT OR IGNORE INTO notice_reads(nid,pid,ts) VALUES(?,?,?)", (nid, session["parent"], datetime.now().isoformat(" ", "seconds")))
    db().commit()
    return redirect(url_for("parent_home") + "#notices")


# ======================= Class Teacher portal (separate login, own pages) =======================
SECTIONS = ["A", "B", "C", "D", "E", "F"]
T_KINDS = ["Homework", "Circular", "Event", "Holiday", "Exam timetable", "Other"]


def _t_assign(tid):
    return [(r["cls"], r["section"]) for r in db().execute("SELECT cls, section FROM class_teacher_assign WHERE tid=? ORDER BY rowid", (tid,))]


def _alabel(cls, sec):
    return f"Class {cls}" + (f" · {sec}" if sec else "")


def _t_students(assign, only=None):
    """Active students of the teacher's assigned classes/sections (optionally one assignment)."""
    pairs = [only] if only else assign
    out = [s for s in active_students()
           if any(s.get("cls") == c and (not sec or (s.get("section") or "") == sec) for c, sec in pairs)]
    return sorted(out, key=lambda r: (CLASSES.index(r["cls"]), r.get("section") or "", int(r["roll"]) if str(r.get("roll", "")).isdigit() else 9999,
                                      (r.get("name") or "").lower()))


def _pick(assign):
    """Selected assignment from ?c=5|A (must be one of the teacher's own)."""
    raw = request.values.get("c", "")
    if "|" in raw:
        c, s = raw.split("|", 1)
        if (c, s) in assign:
            return (c, s)
    return assign[0] if assign else None


def teacher_required(f):
    @wraps(f)
    def wrapper(*a, **k):
        tid = session.get("teacher")
        row = db().execute("SELECT * FROM class_teachers WHERE id=? AND active=1", (tid,)).fetchone() if tid else None
        if row is None:
            session.pop("teacher", None)
            session.pop("tname", None)
            return redirect(url_for("teacher_login"))
        if row["must_change"] and request.endpoint not in ("teacher_password", "teacher_logout"):
            flash("Welcome! Please set your own new password to continue.")
            return redirect(url_for("teacher_password"))
        g.t, g.assign = row, _t_assign(row["id"])
        return f(*a, **k)
    return wrapper


@app.after_request
def _teacher_headers(resp):
    if request.path.startswith("/teacher"):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /teacher\nDisallow: /parent\nDisallow: /principal\nDisallow: /m/\nDisallow: /students/\nDisallow: /login\n", mimetype="text/plain")


@app.route("/teacher/manifest.webmanifest")
def teacher_manifest():
    m = {"name": "Class Teacher Portal - " + SCHOOL, "short_name": "RK Teachers", "start_url": "/teacher", "scope": "/teacher/", "display": "standalone",
         "background_color": "#ffffff", "theme_color": "#7b2d8e",
         "icons": [{"src": url_for("static", filename="icon-192.png"), "sizes": "192x192", "type": "image/png"},
                   {"src": url_for("static", filename="logo.png"), "sizes": "512x512", "type": "image/png"}]}
    return Response(json.dumps(m), mimetype="application/manifest+json")


@app.route("/teacher/login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "GET" and session.get("teacher"):
        return redirect(url_for("teacher_home"))
    if request.method == "POST":
        u, pw = request.form.get("username", "").strip().lower(), request.form.get("password", "")
        k1, k2 = f"teacher:{request.remote_addr}", f"teacheru:{u}"
        if locked(k1) or locked(k2):
            flash("Too many wrong attempts. Please wait 10 minutes and try again.")
            return render_template("teacher_login.html")
        row = db().execute("SELECT * FROM class_teachers WHERE username=? AND active=1", (u,)).fetchone()
        if row and check_password_hash(row["pw"], pw):
            FAILS.pop(k1, None)
            FAILS.pop(k2, None)
            session["teacher"], session["tname"] = row["id"], row["name"]
            db().execute("UPDATE class_teachers SET last_login=? WHERE id=?", (datetime.now().isoformat(" ", "seconds"), row["id"]))
            db().commit()
            audit("Teacher login")
            return redirect(url_for("teacher_home"))
        note_fail(k1)
        note_fail(k2)
        flash("Wrong username or password.")
    return render_template("teacher_login.html")


@app.route("/teacher/logout")
def teacher_logout():
    session.pop("teacher", None)
    session.pop("tname", None)
    return redirect(url_for("teacher_login"))


@app.route("/teacher/password", methods=["GET", "POST"])
@teacher_required
def teacher_password():
    if request.method == "POST":
        cur, new, again = (request.form.get(k, "") for k in ("current", "new", "again"))
        if not check_password_hash(g.t["pw"], cur):
            flash("The current password is wrong.")
        elif len(new) < 6:
            flash("The new password must have at least 6 characters.")
        elif new != again:
            flash("The two new passwords do not match.")
        elif new == cur:
            flash("Please choose a different password from the old one.")
        else:
            db().execute("UPDATE class_teachers SET pw=?, must_change=0 WHERE id=?", (generate_password_hash(new), g.t["id"]))
            db().commit()
            audit("Teacher changed password")
            flash("Your password was changed.")
            return redirect(url_for("teacher_home"))
    return render_template("t_password.html", forced=bool(g.t["must_change"]))


@app.route("/teacher")
@teacher_required
def teacher_home():
    today_s, th = date.today().isoformat(), thresholds()
    studs = _t_students(g.assign)
    ids = [s["id"] for s in studs]
    cards = []
    for c, sec in g.assign:
        grp = _t_students(g.assign, (c, sec))
        gid = [s["id"] for s in grp]
        rows = db().execute(f"SELECT status FROM att_daily WHERE d=? AND sid IN ({','.join('?' * len(gid))})", [today_s] + gid).fetchall() if gid else []
        cards.append(dict(cls=c, sec=sec, label=_alabel(c, sec), n=len(grp), marked=bool(rows), present=sum(1 for r in rows if r["status"] == "P"),
                          absent=sum(1 for r in rows if r["status"] == "A"), leave=sum(1 for r in rows if r["status"] == "L"), key=f"{c}|{sec}"))
    trend = []
    if ids:
        start = (date.today() - timedelta(days=13)).isoformat()
        for r in db().execute(f"SELECT d, SUM(status='P') p, COUNT(*) w FROM att_daily WHERE sid IN ({','.join('?' * len(ids))}) AND d>=? GROUP BY d ORDER BY d", ids + [start]):
            trend.append((r["d"][5:], round(r["p"] / r["w"] * 100) if r["w"] else 0))
    mine = {str(i) for i in ids}
    att = RP.attention(studs, [r for r in rows_of("exams") if str(r.get("sid")) in mine], att_months(), current_ay(), th["pass_mark"], th["att_alert"], th["drop_alert"])
    my_notices = [n for n in rows_of("notices") if str(n.get("by_tid")) == str(g.t["id"])][:4]
    upcoming = sorted(r for r in get_site().get("calendar", []) if len(r) >= 2 and r[0] >= today_s)[:3]
    return render_template("t_dashboard.html", cards=cards, n_students=len(studs), trend=trend, att=att[:5], n_att=len(att), notices=my_notices,
                           upcoming=upcoming, unmarked=[c for c in cards if not c["marked"] and c["n"]])


@app.route("/teacher/students")
@teacher_required
def t_students():
    sel, q = request.args.get("c", ""), request.args.get("q", "").strip().lower()
    only = _pick(g.assign) if sel else None
    studs = [s for s in _t_students(g.assign, only) if not q or any(q in str(s.get(k, "")).lower() for k in ("name", "roll", "parent", "phone"))]
    return render_template("t_students.html", studs=studs, sel=f"{only[0]}|{only[1]}" if only else "", q=request.args.get("q", ""),
                           assigns=[(f"{c}|{s}", _alabel(c, s)) for c, s in g.assign])


def _own_student(sid):
    s = next((x for x in _t_students(g.assign) if x["id"] == sid), None)
    if s is None:
        abort(404)
    return s


@app.route("/teacher/student/<int:sid>")
@teacher_required
def t_student(sid):
    kid = _own_student(sid)
    R = child_report(kid)
    return render_template("t_student.html", kid=kid, R=R, kinds=["Academic", "Behaviour", "Strength", "Needs improvement", "General"],
                           info=[(f["label"], kid.get(f["key"])) for f in fields_of("students") if kid.get(f["key"]) and f["key"] not in ("name", "cls", "roll", "section", "photo")])


@app.post("/teacher/student/<int:sid>/remark")
@teacher_required
def t_remark(sid):
    kid = _own_student(sid)
    text, kind = request.form.get("remark", "").strip()[:500], request.form.get("kind", "General")
    if text:
        rec = dict(sid=str(sid), student=kid.get("name", ""), cls=kid.get("cls", ""), date=date.today().isoformat(), kind=kind, remark=text, by=g.t["name"])
        db().execute("INSERT INTO records(module,data) VALUES('remarks',?)", (json.dumps(rec),))
        db().commit()
        audit("Teacher remark", f"{kid.get('name')}")
        flash("Remark saved.")
    return redirect(url_for("t_student", sid=sid) + "#remarks")


@app.route("/teacher/student/<int:sid>/report")
@teacher_required
def t_report_card(sid):
    return _report_card_view(_own_student(sid), url_for("t_student", sid=sid))


@app.route("/teacher/attendance", methods=["GET", "POST"])
@teacher_required
def t_attendance():
    only = _pick(g.assign)
    day = request.values.get("date", date.today().isoformat())
    studs = _t_students(g.assign, only) if only else []
    if request.method == "POST" and studs:
        for s in studs:
            v = request.form.get("s_" + str(s["id"]), "P")
            db().execute("INSERT OR REPLACE INTO att_daily(sid,d,status) VALUES(?,?,?)", (s["id"], day, v if v in ("P", "A", "L") else "P"))
        db().commit()
        audit("Teacher attendance", f"{_alabel(*only)} {day}")
        flash(f"Attendance saved for {_alabel(*only)} on {day}.")
        return redirect(url_for("t_attendance", c=f"{only[0]}|{only[1]}", date=day))
    cur = {r["sid"]: r["status"] for r in db().execute("SELECT sid,status FROM att_daily WHERE d=?", (day,))}
    return render_template("t_attendance.html", studs=studs, cur=cur, day=day, sel=f"{only[0]}|{only[1]}" if only else "",
                           assigns=[(f"{c}|{s}", _alabel(c, s)) for c, s in g.assign])


@app.route("/teacher/marks", methods=["GET", "POST"])
@teacher_required
def t_marks():
    only = _pick(g.assign)
    q = request.values
    exam, subject = q.get("exam", "").strip()[:60], q.get("subject", "").strip()[:60]
    date_, mx = q.get("date", date.today().isoformat()), q.get("max", "100") or "100"
    studs = _t_students(g.assign, only) if only else []
    existing = {}
    if only and exam and subject:
        mine = {str(s["id"]) for s in studs}
        for r in rows_of("exams"):
            if str(r.get("sid")) in mine and r.get("exam") == exam and r.get("subject") == subject and (r.get("date") or "")[:7] == date_[:7]:
                existing[str(r["sid"])] = r
    if request.method == "POST" and studs and exam and subject:
        _ensure_exam(exam)
        absent, n = set(request.form.getlist("absent")), 0
        for s in studs:
            sid = str(s["id"])
            got, is_abs = request.form.get("m_" + sid, "").strip(), sid in absent
            if got == "" and not is_abs:
                continue
            rec = dict(sid=sid, student=s.get("name", ""), cls=s.get("cls", ""), exam=exam, subject=subject, date=date_, max=mx,
                       marks="" if is_abs else got, attended="Absent" if is_abs else "Attended", remarks=(existing.get(sid) or {}).get("remarks", ""))
            if sid in existing:
                db().execute("UPDATE records SET data=? WHERE id=?", (json.dumps(rec), existing[sid]["id"]))
            else:
                db().execute("INSERT INTO records(module,data) VALUES('exams',?)", (json.dumps(rec),))
            n += 1
        db().commit()
        audit("Teacher marks", f"{_alabel(*only)} {exam} {subject}: {n}")
        flash(f"Marks saved for {n} student(s).")
        return redirect(url_for("t_marks", c=f"{only[0]}|{only[1]}", exam=exam, subject=subject, date=date_, max=mx))
    return render_template("t_marks.html", studs=studs, existing=existing, exam=exam, subject=subject, date=date_, max=mx,
                           sel=f"{only[0]}|{only[1]}" if only else "", assigns=[(f"{c}|{s}", _alabel(c, s)) for c, s in g.assign],
                           names=_exam_names(), subjects=DEFAULT_SUBJECTS, pass_mark=thresholds()["pass_mark"])


@app.route("/teacher/reports")
@teacher_required
def t_report():
    only, exam, ay, th = _pick(g.assign), request.args.get("exam", ""), current_ay(), thresholds()
    studs = _t_students(g.assign, only) if only else []
    mine = {str(s["id"]) for s in studs}
    data = RP.class_exam(studs, [r for r in rows_of("exams") if str(r.get("sid")) in mine], only[0], exam, ay, th["pass_mark"]) if only and exam else None
    att = [a for a in RP.attention(studs, [r for r in rows_of("exams") if str(r.get("sid")) in mine], att_months(), ay, th["pass_mark"], th["att_alert"], th["drop_alert"])]
    return render_template("t_report.html", data=data, exam=exam, att=att, names=_exam_names(), sel=f"{only[0]}|{only[1]}" if only else "",
                           assigns=[(f"{c}|{s}", _alabel(c, s)) for c, s in g.assign], heat=RP.heat, th=th)


@app.route("/teacher/notices", methods=["GET", "POST"])
@teacher_required
def t_notices():
    my_classes = sorted({c for c, _ in g.assign}, key=CLASSES.index)
    if request.method == "POST":
        title, aud = request.form.get("title", "").strip()[:120], request.form.get("audience", "")
        if not title or aud not in my_classes:
            flash("Please type a title and choose one of your classes.")
        else:
            rec = dict(title=title, kind=request.form.get("kind") if request.form.get("kind") in T_KINDS else "Other", audience=aud,
                       date=request.form.get("date") or date.today().isoformat(), details=request.form.get("details", "").strip()[:1500],
                       by_tid=str(g.t["id"]), by=g.t["name"])
            db().execute("INSERT INTO records(module,data) VALUES('notices',?)", (json.dumps(rec),))
            db().commit()
            audit("Teacher notice", title)
            flash("Posted. Parents of that class will see it in their portal.")
        return redirect(url_for("t_notices"))
    mine = [n for n in rows_of("notices") if str(n.get("by_tid")) == str(g.t["id"])]
    reads = Counter(x["nid"] for x in db().execute("SELECT nid FROM notice_reads"))
    return render_template("t_notices.html", items=mine, classes=my_classes, kinds=T_KINDS, reads=reads)


@app.post("/teacher/notices/<int:nid>/delete")
@teacher_required
def t_notice_delete(nid):
    r = db().execute("SELECT data FROM records WHERE id=? AND module='notices'", (nid,)).fetchone()
    if r is None or str(json.loads(r["data"]).get("by_tid")) != str(g.t["id"]):
        abort(404)
    db().execute("DELETE FROM records WHERE id=?", (nid,))
    db().commit()
    audit("Teacher notice deleted")
    flash("Deleted.")
    return redirect(url_for("t_notices"))


# ---------- Admin: manage class teachers and their class/section assignments ----------
def _all_sections():
    return sorted(set(SECTIONS) | {(s.get("section") or "").strip() for s in rows_of("students") if (s.get("section") or "").strip()})


def _gen_pw():
    return "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))


def _save_assign(tid):
    db().execute("DELETE FROM class_teacher_assign WHERE tid=?", (tid,))
    for v in request.form.getlist("asg"):
        if "|" in v:
            c, s = v.split("|", 1)
            if c in CLASSES and (s == "" or re.fullmatch(r"[A-Za-z0-9]{1,3}", s)):
                db().execute("INSERT OR IGNORE INTO class_teacher_assign(tid,cls,section) VALUES(?,?,?)", (tid, c, s.upper()))


@app.route("/principal/class-teachers", methods=["GET", "POST"])
@admin_only
def class_teachers():
    if request.method == "POST":
        f = request.form
        name, u = f.get("name", "").strip()[:60], re.sub(r"\s+", "", f.get("username", "").lower())
        if not name or not re.fullmatch(r"[a-z0-9._-]{3,30}", u):
            flash("Enter the teacher's name and a username of 3-30 letters or digits (no spaces).")
        elif db().execute("SELECT 1 FROM class_teachers WHERE username=?", (u,)).fetchone():
            flash("That username is already used.")
        else:
            pw = f.get("password", "").strip() or _gen_pw()
            tid = db().execute("INSERT INTO class_teachers(name,username,phone,pw,active,must_change) VALUES(?,?,?,?,1,1)",
                               (name, u, f.get("phone", "").strip()[:20], generate_password_hash(pw))).lastrowid
            _save_assign(tid)
            db().commit()
            audit("Class teacher created", name)
            flash(f"Class teacher created.  Username: {u}   Password: {pw}   - share these privately. The teacher must set a new password at first login. Portal address: {url_for('teacher_login', _external=True)}")
        return redirect(url_for("class_teachers"))
    rows = []
    for t in db().execute("SELECT * FROM class_teachers ORDER BY id DESC"):
        a = _t_assign(t["id"])
        rows.append(dict(t, assign=[_alabel(c, s) for c, s in a], n=len(_t_students(a))))
    return render_template("class_teachers.html", rows=rows, classes=CLASSES, sections=_all_sections(), chosen=set())


@app.route("/principal/class-teachers/<int:tid>", methods=["GET", "POST"])
@admin_only
def class_teacher_edit(tid):
    t = db().execute("SELECT * FROM class_teachers WHERE id=?", (tid,)).fetchone()
    if t is None:
        abort(404)
    if request.method == "POST":
        f = request.form
        if f.get("act") == "delete":
            for q in ("DELETE FROM class_teacher_assign WHERE tid=?", "DELETE FROM class_teachers WHERE id=?"):
                db().execute(q, (tid,))
            db().commit()
            audit("Class teacher deleted", t["name"])
            flash("Class teacher deleted.")
            return redirect(url_for("class_teachers"))
        u = re.sub(r"\s+", "", f.get("username", "").lower())
        if not re.fullmatch(r"[a-z0-9._-]{3,30}", u) or db().execute("SELECT 1 FROM class_teachers WHERE username=? AND id<>?", (u, tid)).fetchone():
            flash("Choose a different username (3-30 letters or digits, not already used).")
            return redirect(url_for("class_teacher_edit", tid=tid))
        pw, msg = t["pw"], "Saved."
        mc = t["must_change"]
        if f.get("reset"):
            new = _gen_pw()
            pw, mc, msg = generate_password_hash(new), 1, f"Saved. New password: {new} - share it privately. The teacher must set their own at the next login."
        db().execute("UPDATE class_teachers SET name=?, username=?, phone=?, active=?, pw=?, must_change=? WHERE id=?",
                     (f.get("name", "").strip()[:60] or t["name"], u, f.get("phone", "").strip()[:20], 1 if f.get("active") else 0, pw, mc, tid))
        _save_assign(tid)
        db().commit()
        audit("Class teacher updated", t["name"])
        flash(msg)
        return redirect(url_for("class_teachers"))
    return render_template("class_teacher_edit.html", t=t, classes=CLASSES, sections=_all_sections(), chosen={f"{c}|{s}" for c, s in _t_assign(tid)})


init_db()
if __name__ == "__main__":
    app.run(debug=True)
