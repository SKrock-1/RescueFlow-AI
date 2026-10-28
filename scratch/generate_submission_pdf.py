import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def create_submission_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A'),
        alignment=1, # Center
        spaceAfter=10
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#475569'),
        alignment=1,
        spaceAfter=15
    )
    
    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=12,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=6
    )
    
    meta_label = ParagraphStyle(
        'MetaLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#0F172A')
    )
    
    meta_val = ParagraphStyle(
        'MetaVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#334155')
    )
    
    caption_style = ParagraphStyle(
        'Caption',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#2563EB'),
        alignment=1,
        spaceBefore=4,
        spaceAfter=8
    )

    story = []

    # Title & Subtitle
    story.append(Paragraph("AGENTIC AI SUBMISSION — CA1", title_style))
    story.append(Paragraph("RescueFlow AI: Autonomous Multi-Agent Last-Mile Delivery Exception (NDR) Resolution Engine for Shopify", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#2563EB'), spaceBefore=0, spaceAfter=12))

    # Meta Table
    meta_data = [
        [Paragraph("<b>Student Name:</b>", meta_label), Paragraph("Sonu Kumar", meta_val),
         Paragraph("<b>Email:</b>", meta_label), Paragraph("sonukumar3108ch@gmail.com", meta_val)],
        [Paragraph("<b>Course:</b>", meta_label), Paragraph("Agentic AI (CA1 Submission)", meta_val),
         Paragraph("<b>Architecture:</b>", meta_label), Paragraph("Plan-Act-Observe Autonomous Tool-Calling", meta_val)],
        [Paragraph("<b>Tech Stack:</b>", meta_label), Paragraph("Python 3.11+, Streamlit, SQLite/SQLAlchemy, Shopify REST API", meta_val),
         Paragraph("<b>LLM Providers:</b>", meta_label), Paragraph("NVIDIA NIM (Mistral-Nemotron / Muse-Glimmer) & Groq", meta_val)]
    ]
    meta_table = Table(meta_data, colWidths=[1.1*inch, 2.3*inch, 1.1*inch, 2.5*inch])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 0.8, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0,0), (-1,-1), 0.4, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # Project Brief
    story.append(Paragraph("Project Brief (200 Words)", h1_style))
    brief_text = (
        "Last-mile delivery failures, commonly termed Non-Delivery Reports (NDRs), represent one of the costliest pain points in "
        "modern e-commerce logistics, driving high return-to-origin (RTO) rates and customer attrition. <b>RescueFlow AI</b> is an "
        "enterprise-grade autonomous decision-making system engineered to autonomously resolve delivery exceptions for Shopify merchants in real time. "
        "Operating on a robust <b>Plan-Act-Observe</b> agentic loop backed by deterministic operational guardrails, the agent intercepts delivery failure "
        "webhooks and analyzes customer behavioral attributes synced directly from the Shopify Admin REST API, including VIP loyalty tiers, preferred delivery "
        "time slots, and office or residential premises constraints.<br/><br/>"
        "Using specialized tool calling, RescueFlow AI queries live fleet capacity, computes optimal rescheduling windows that strictly adhere to commercial "
        "operating hours (09:00–18:00), reassigns high-suitability delivery personnel, and records transactional database mutations. To guarantee business safety, "
        "deterministic policy guardrails prevent duplicate reassignments and enforce vehicle load constraints. Once resolved, the system executes seamless two-way "
        "synchronization by updating Shopify order tags and audit notes, while simultaneously triggering customer-facing WhatsApp and SMS interactive dispatches. "
        "By replacing sluggish manual support queues with sub-second autonomous intervention, RescueFlow AI drastically slashes delivery failure rates and elevates buyer retention."
    )
    story.append(Paragraph(brief_text, body_style))

    # Objectives
    story.append(Paragraph("Core Project Objectives", h1_style))
    obj_text = (
        "<b>1. Autonomous Multi-Step Exception Resolution:</b> Implement an end-to-end agentic Plan-Act-Observe loop equipped with specialized "
        "Python tools (customer profiling, slot discovery, courier reassignment, address verification) that autonomously resolves delivery exceptions without human intervention.<br/>"
        "<b>2. Strict Operational Guardrails & Constraint Enforcement:</b> Enforce non-negotiable deterministic rules including commercial address operating hours "
        "(09:00–18:00), courier vehicle load/capacity limits, and VIP buyer SLA prioritization to guarantee enterprise-grade decision safety.<br/>"
        "<b>3. Bidirectional E-Commerce Integration (Shopify Admin API):</b> Enable real-time 2-way data flow that ingests live customer orders, tracks delivery failure events, "
        "writes resolution tags (e.g., <i>rf-reschedule_delivery</i>, <i>rescueflow-rescued</i>), and logs structured merchant notes.<br/>"
        "<b>4. Real-Time Customer & Fleet Synchronization:</b> Synthesize customer preferences to autonomously dispatch simulated WhatsApp/SMS notifications and driver notes, "
        "maximizing first-attempt re-delivery success rates."
    )
    story.append(Paragraph(obj_text, body_style))
    story.append(Spacer(1, 10))

    # Screenshots Section
    story.append(Paragraph("Output & Verification Screenshots", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceBefore=2, spaceAfter=10))

    brain_dir = r"C:\Users\sonu kumar\.gemini\antigravity-ide\brain\ec0e6dbd-32c9-4dab-ac12-c4047404cba0"

    shots = [
        {
            "file": os.path.join(brain_dir, "tab1_shopify_orders_1789379090579.png"),
            "title": "Figure 1: Live Shopify Operations Console & Order Rescue Pipeline",
            "desc": "Real-time Shopify store sync showing active orders, VIP badges, time window preferences, and live autonomous rescue status with 2-way sync to Shopify Admin."
        },
        {
            "file": os.path.join(brain_dir, "whatsapp_mockup_ui_1789330596422.png"),
            "title": "Figure 2: Real-Time WhatsApp Customer Dispatch & Order Resolution",
            "desc": "Simulated WhatsApp dispatch tailored to buyer's specific slot preference with executive resolution summary and verified Shopify order tags."
        },
        {
            "file": os.path.join(brain_dir, "tab2_agent_reasoning_1789379103783.png"),
            "title": "Figure 3: Agent Reasoning Trace (Plan-Act-Observe Multi-Step Tool Execution)",
            "desc": "Full inspectable trace demonstrating sequential tool invocations (get_order -> get_customer_profile -> find_available_delivery_slots -> reschedule_delivery)."
        },
        {
            "file": os.path.join(brain_dir, "tab3_fleet_couriers_1789379120343.png"),
            "title": "Figure 4: Fleet Couriers Management & Cross-Order Customer Memory",
            "desc": "Live fleet monitoring with vehicle types, courier shift status, delivery capacities, and persistent customer operational memory entries."
        },
        {
            "file": os.path.join(brain_dir, "decision_flow_diagram_1789323313942.png"),
            "title": "Figure 5: Enterprise Agent Decision Flow & Guardrail Architecture",
            "desc": "System architecture diagram illustrating Inbound NDR Webhooks, Agent Reasoner, Guardrails Engine, Tool Execution, and Outbound 2-Way Shopify Sync."
        }
    ]

    for i, shot in enumerate(shots):
        if os.path.exists(shot["file"]):
            elem = []
            elem.append(Paragraph(shot["title"], caption_style))
            # Width = 6.8 inch, height proportional ~ 3.4 inch
            elem.append(Image(shot["file"], width=6.8*inch, height=3.4*inch))
            elem.append(Spacer(1, 4))
            elem.append(Paragraph(f"<b>Description:</b> {shot['desc']}", body_style))
            elem.append(Spacer(1, 10))
            story.append(KeepTogether(elem))
            if i in [1, 3]:  # Clean page breaks
                story.append(PageBreak())

    doc.build(story)
    print(f"[OK] Generated PDF successfully at: {output_path}")

if __name__ == "__main__":
    out_pdf = r"c:\Users\sonu kumar\OneDrive - Lovely Professional University\Desktop\Agent__\RescueFlow_AI_Output_Screenshots.pdf"
    create_submission_pdf(out_pdf)
