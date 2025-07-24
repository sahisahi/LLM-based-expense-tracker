from fastapi import FastAPI, Query, Request
from pydantic import BaseModel
from typing import Optional
import datetime
import requests
import os
import json
import matplotlib.pyplot as plt
from fastapi.responses import FileResponse
from collections import defaultdict

app = FastAPI()

WHATSAPP_TOKEN = 'EAA6atfK47iMBO719DBDtChfnSv0KEV1vLNUBYbZABcksAvubTnY1YkQWt97wn1ZCid8ikuT6ZBNIsY4lttNZCa6Dhy0ZBGR96wnSwEhgq4iphnRvjGRyPDX8cYzjCZB7ZChxTVcNSesCSRZAn7xlAqg7Cn00gF8RgpNqqbrbtU9NdchiKUE64HhRK171TWcMprwCnZCvnX4RCk97EXkcF204kP8Yj60snRd3ICRk2zYH4W7cZD'
PHONE_NUMBER_ID = '731645456691373'

DATA_FILE = "expenses.json"
MEMORY_FILE = "memory.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        expense_data = json.load(f)
else:
    expense_data = {}

if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r") as f:
        memory = json.load(f)
else:
    memory = {}

class Expense(BaseModel):
    category: str
    amount: float
    description: Optional[str] = None

@app.post("/expense/{day}")
def add_expense(day: str, expense: Expense):
    if day not in expense_data:
        expense_data[day] = []
    expense_data[day].append(expense.dict())

    with open(DATA_FILE, "w") as f:
        json.dump(expense_data, f)

    return {"date": day, **expense.dict()}

@app.get("/summary")
def get_summary(start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None)):
    start_date = start_date or memory.get("start_date")
    end_date = end_date or memory.get("end_date")

    if not start_date:
        return {"error": "Please provide start_date at least once."}

    try:
        start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    memory.update({"start_date": start_date, "end_date": end_date})
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f)

    filtered_data = {}
    for date_str, records in expense_data.items():
        try:
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if date_obj >= start and (not end or date_obj <= end):
            filtered_data[date_str] = records

    if not filtered_data:
        return {"summary": "Wow, so thrifty! No spending found in that period."}

    prompt = f"""You're a sarcastic, witty personal finance assistant. Summarize this spending report from {start_date} to {end_date or 'latest'} with dry humor:\n\n{filtered_data}"""

    headers = {
        "Authorization": f"Bearer {os.environ.get('GROQ_API_KEY')}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gemma2-9b-it",
        "messages": [
            {"role": "system", "content": "You summarize personal finance with sarcasm."},
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data)
        result = response.json()

        if "choices" not in result:
            return {"error": "Groq API error", "details": result}

        return {"summary": result["choices"][0]["message"]["content"]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/chart/categories")
def chart_categories():
    category_totals = {}
    for records in expense_data.values():
        for r in records:
            category_totals[r['category']] = category_totals.get(r['category'], 0) + r['amount']

    if not category_totals:
        return {"error": "No data to generate chart."}

    labels = list(category_totals.keys())
    sizes = list(category_totals.values())

    plt.figure(figsize=(6, 6))
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140)
    plt.title("Spending by Category")
    chart_path = "category_chart.png"
    plt.savefig(chart_path)
    plt.close()

    return chart_path

@app.get("/chart/timeline")
def chart_timeline(by: str = "month"):
    timeline = defaultdict(lambda: defaultdict(float))

    for date_str, records in expense_data.items():
        try:
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        key = (
            f"{date_obj.year}-{date_obj.month:02d}" if by == "month"
            else f"{date_obj.year}"
        )

        for r in records:
            timeline[key][r['category']] += r['amount']

    if not timeline:
        return {"error": "No data to generate timeline chart."}

    periods = sorted(timeline.keys())
    categories = set(cat for data in timeline.values() for cat in data)

    category_data = {cat: [timeline[period].get(cat, 0) for period in periods] for cat in categories}

    plt.figure(figsize=(10, 6))
    width = 0.8 / len(categories)

    for i, (cat, values) in enumerate(category_data.items()):
        x_pos = [j + i * width for j in range(len(periods))]
        plt.bar(x_pos, values, width=width, label=cat)

    plt.xticks([r + width * (len(categories)-1) / 2 for r in range(len(periods))], periods, rotation=45)
    plt.xlabel(by.capitalize())
    plt.ylabel("Amount")
    plt.title(f"Spending by {by.capitalize()} and Category")
    plt.legend()
    plt.tight_layout()

    chart_path = "timeline_chart.png"
    plt.savefig(chart_path)
    plt.close()

    return chart_path

@app.post("/webhook")
async def receive_whatsapp_webhook(request: Request):
    body = await request.json()
    print("Webhook Received:", json.dumps(body, indent=2))

    try:
        entry = body['entry'][0]
        change = entry['changes'][0]
        value = change['value']
        messages = value.get('messages')

        if messages:
            from_number = messages[0]['from']
            msg_body = messages[0]['text']['body'].strip()

            if msg_body.lower().startswith("add"):
                try:
                    parts = msg_body.split(maxsplit=4)
                    _, date_str, category, amount_str, description = parts
                    amount = float(amount_str)

                    new_expense = {
                        "category": category,
                        "amount": amount,
                        "description": description
                    }

                    if date_str not in expense_data:
                        expense_data[date_str] = []

                    expense_data[date_str].append(new_expense)

                    with open(DATA_FILE, "w") as f:
                        json.dump(expense_data, f)

                    reply = f"✅ Added ₹{amount} for {category} on {date_str} – \"{description}\""
                except:
                    reply = "⚠️ Couldn't add expense. Format: add YYYY-MM-DD category amount description"

            elif msg_body.lower().startswith("summary"):
                result = get_summary(start_date=memory.get("start_date", datetime.date.today().strftime("%Y-%m-%d")))
                reply = result.get("summary", "No summary available.")

            elif msg_body.lower() == "chart categories":
                chart_path = chart_categories()
                reply = "[Chart generated: category_chart.png]"
                # Optional: send chart via media upload API

            elif msg_body.lower() == "chart timeline":
                chart_path = chart_timeline()
                reply = "[Chart generated: timeline_chart.png]"

            else:
                reply = f"You said: {msg_body} 👀"

            url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": from_number,
                "text": {"body": reply}
            }

            r = requests.post(url, headers=headers, json=payload)
            print("Reply status:", r.status_code, r.text)

    except Exception as e:
        print("Error handling webhook:", e)

    return {"status": "received"}
