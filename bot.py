import asyncio
import requests
import random
import string
import time
import os
import threading
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext

import firebase_admin
from firebase_admin import credentials, db

# ============================================
# CONFIGURATION
# ============================================
TOKEN = "8581053403:AAFF1bI50_EdoQDdvdgScrAwSR44HYoBi6I"
API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"

if not os.path.exists("serviceAccount.json"):
    print("❌ ERROR: serviceAccount.json file not found!")
    exit(1)

try:
    cred = credentials.Certificate("serviceAccount.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://deviceid-d9c40-default-rtdb.firebaseio.com/'
    })
    print("✅ Firebase connected!")
except Exception as e:
    print(f"❌ Firebase error: {e}")
    exit(1)

users = {}
sent_results = {}
sent_predictions = {}
last_processed_minute = -1

# ============================================
# DEVICE FUNCTIONS
# ============================================

def generate_device_id():
    return "WIN-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def get_or_create_device_id(chat_id):
    try:
        ref = db.reference(f"telegram_users/{chat_id}")
        data = ref.get()
        if data and data.get('device_id'):
            return data['device_id']
        else:
            new_id = generate_device_id()
            ref.set({
                "device_id": new_id,
                "chat_id": chat_id,
                "created_at": int(time.time() * 1000)
            })
            return new_id
    except:
        return generate_device_id()

def check_device_access(device_id):
    try:
        ref = db.reference(f"deviceAccess/{device_id}")
        data = ref.get()
        if data and data.get("accessGranted") and data.get("expiry") > int(time.time() * 1000):
            return True
        return False
    except:
        return False

# ============================================
# EXACT L1-L13 PREDICTION LOGIC
# ============================================

def classify(n: int) -> str:
    return "BIG" if n >= 5 else "SMALL"

def L1(history: List[int]) -> str:
    if not history or len(history) < 10:
        return "BIG"
    diff = history[0] - history[9]
    return "BIG" if diff >= 5 else "SMALL"

def L2(history: List[int]) -> str:
    labels = [classify(x) for x in history[:5]]
    if len(labels) >= 3 and labels[0] == labels[1] == labels[2]:
        return "SMALL" if labels[0] == "BIG" else "BIG"
    return labels[0]

def L3(history: List[int]) -> str:
    labels = [classify(x) for x in history[:5]]
    if len(labels) >= 3 and labels[0] == labels[1] == labels[2]:
        return labels[0]
    return "SMALL" if labels[0] == "BIG" else "BIG"

def L4(history: List[int]) -> str:
    labels = [classify(x) for x in history[:20]]
    big = sum(1 for l in labels if l == "BIG")
    small = len(labels) - big
    
    cons_big, cons_small = 0, 0
    for lab in labels:
        if lab == "BIG":
            if cons_small == 0:
                cons_big += 1
            else:
                break
        else:
            if cons_big == 0:
                cons_small += 1
            else:
                break
    
    avg10 = sum(history[:10]) / min(len(history), 10) if history else 5
    
    big_votes, small_votes = 0, 0
    if big > small:
        big_votes += 1
    elif small > big:
        small_votes += 1
    if cons_big >= 2:
        big_votes += 1
    elif cons_small >= 2:
        small_votes += 1
    if avg10 >= 5:
        big_votes += 1
    else:
        small_votes += 1
    
    if big_votes > small_votes:
        return "BIG"
    if small_votes > big_votes:
        return "SMALL"
    return labels[0]

def L5(history: List[int]) -> str:
    if len(history) < 8:
        return classify(history[0] if history else 5)
    
    labels = [classify(x) for x in history[:80]]
    big_count = sum(1 for l in labels if l == "BIG")
    small_count = len(labels) - big_count
    recent_side = labels[0]
    
    streak = 1
    for i in range(1, len(labels)):
        if labels[i] == labels[i-1]:
            streak += 1
        else:
            break
    
    if streak >= 4:
        return "SMALL" if recent_side == "BIG" else "BIG"
    if big_count > small_count + 3:
        return "SMALL"
    if small_count > big_count + 3:
        return "BIG"
    return recent_side

def L6(history: List[int]) -> str:
    labels = [classify(x) for x in history[:10]]
    if len(labels) < 4:
        return "BIG"
    
    if labels[0] == labels[1] == labels[2]:
        return "SMALL" if labels[0] == "BIG" else "BIG"
    
    if len(labels) >= 4 and labels[0] != labels[1] and labels[1] != labels[2] and labels[2] != labels[3] and labels[0] == labels[2] and labels[1] == labels[3]:
        return "SMALL" if labels[3] == "BIG" else "BIG"
    
    big = sum(1 for l in labels if l == "BIG")
    small = len(labels) - big
    if big > small + 2:
        return "SMALL"
    if small > big + 2:
        return "BIG"
    return labels[0]

def L7(history: List[int]) -> str:
    return classify(history[0] if history else 0)

def L8(history: List[int]) -> str:
    labels = [classify(x) for x in history[:10]]
    if len(labels) < 4:
        return "BIG"
    
    if labels[0] == labels[1] == labels[2]:
        return "SMALL" if labels[0] == "BIG" else "BIG"
    
    if len(labels) >= 4 and labels[0] != labels[1] and labels[1] != labels[2] and labels[2] != labels[3] and labels[0] == labels[2] and labels[1] == labels[3]:
        return "SMALL" if labels[3] == "BIG" else "BIG"
    
    big = sum(1 for l in labels if l == "BIG")
    return "SMALL" if big > 5 else "BIG"

def L9(history: List[int]) -> str:
    labels = [classify(x) for x in history[:20]]
    big_score, small_score = 0.0, 0.0
    
    if len(labels) >= 3 and labels[0] == labels[1] == labels[2]:
        if labels[0] == "BIG":
            small_score += 3
        else:
            big_score += 3
    
    big_count = sum(1 for l in labels if l == "BIG")
    small_count = len(labels) - big_count
    big_score += big_count * 0.4
    small_score += small_count * 0.4
    
    if history:
        avg5 = sum(history[:5]) / min(5, len(history))
        if avg5 >= 6:
            big_score += 1.5
        elif avg5 <= 3:
            small_score += 1.5
    
    return "BIG" if big_score >= small_score else "SMALL"

def L10(history: List[int]) -> str:
    labels = [classify(x) for x in history[:20]]
    big, small = 0.0, 0.0
    
    if len(labels) >= 3 and labels[0] == labels[1] == labels[2]:
        if labels[0] == "BIG":
            small += 4
        else:
            big += 4
    else:
        if labels[0] == "BIG":
            big += 1
        else:
            small += 1
    
    big_count = sum(1 for l in labels if l == "BIG")
    small_count = len(labels) - big_count
    big += big_count * 0.5
    small += small_count * 0.5
    
    if history:
        avg5 = sum(history[:5]) / min(5, len(history))
        if avg5 >= 6:
            big += 2
        elif avg5 <= 3:
            small += 2
    
    if len(labels) >= 4 and labels[0] == labels[2] and labels[1] == labels[3] and labels[0] != labels[1]:
        if labels[3] == "BIG":
            small += 3
        else:
            big += 3
    
    if big > small + 5:
        return "SMALL"
    if small > big + 5:
        return "BIG"
    return "BIG" if big >= small else "SMALL"

def L11(history: List[int]) -> str:
    labels = [classify(x) for x in history[:10]]
    if len(labels) >= 3 and labels[0] == labels[1] == labels[2]:
        return "SMALL" if labels[0] == "BIG" else "BIG"
    
    if len(labels) >= 4 and labels[0] == labels[2] and labels[1] == labels[3] and labels[0] != labels[1]:
        return "SMALL" if labels[3] == "BIG" else "BIG"
    
    if len(labels) >= 2 and labels[0] == labels[1]:
        return "SMALL" if labels[0] == "BIG" else "BIG"
    
    last3_big = sum(1 for l in labels[:3] if l == "BIG")
    return "SMALL" if last3_big >= 2 else "BIG"

def L12(history: List[int]) -> str:
    last3 = [classify(x) for x in history[:3]]
    big_count = sum(1 for l in last3 if l == "BIG")
    if big_count == 3:
        return "SMALL"
    if big_count == 0:
        return "BIG"
    return "SMALL" if big_count >= 2 else "BIG"

def L13(history: List[int]) -> str:
    if len(history) < 10:
        return classify(history[0] if history else 5)
    
    size_seq = [classify(x) for x in history[:8]]
    score = 0.0
    weights = [1.8, 1.4, 1.0, 0.6, 0.3, 0.2, 0.1, 0.1]
    
    for i in range(min(len(size_seq), len(weights))):
        if size_seq[i] == "BIG":
            score += weights[i]
        else:
            score -= weights[i]
    
    big_count = sum(1 for l in size_seq if l == "BIG")
    if big_count >= 6:
        return "SMALL"
    if big_count <= 2:
        return "BIG"
    return "BIG" if score >= 0 else "SMALL"

LOGICS = [L1, L2, L3, L4, L5, L6, L7, L8, L9, L10, L11, L12, L13]
LOGIC_WEIGHTS = [20, 24, 24, 28, 26, 25, 18, 24, 30, 32, 26, 22, 35]

def get_weighted_prediction(history: List[int]) -> Tuple[str, int]:
    big_total = 0
    small_total = 0
    for i in range(len(LOGICS)):
        try:
            pred = LOGICS[i](history)
        except:
            pred = "BIG"
        weight = LOGIC_WEIGHTS[i]
        if pred == "BIG":
            big_total += weight
        else:
            small_total += weight
    total = big_total + small_total
    confidence = int((max(big_total, small_total) / total * 100)) if total > 0 else 50
    final_pred = "BIG" if big_total >= small_total else "SMALL"
    return final_pred, confidence

# ============================================
# FETCH GAME DATA
# ============================================

def fetch_game_data():
    try:
        response = requests.get(API_URL + '?t=' + str(int(time.time() * 1000)), timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data and 'data' in data and 'list' in data['data']:
                return [{'number': int(item['number']), 'issueNumber': item['issueNumber']} 
                        for item in data['data']['list'][:20]]
    except Exception as e:
        print(f"API Error: {e}")
    return []

# ============================================
# TELEGRAM COMMANDS
# ============================================

def delete_message(context, chat_id, message_id):
    try:
        context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except:
        pass

def check_access_loop(chat_id, context):
    while True:
        device_id = get_or_create_device_id(chat_id)
        if device_id:
            has_access = check_device_access(device_id)
            if has_access and chat_id not in users:
                if "waiting_msg_id" in users.get(chat_id, {}):
                    delete_message(context, chat_id, users[chat_id]["waiting_msg_id"])
                
                users[chat_id] = {
                    "device_id": device_id,
                    "multiplier": 1,
                    "last_prediction": None,
                    "last_sent_period": None,
                    "user_wins": 0,
                    "user_losses": 0,
                    "win_streak": 0,
                    "loss_streak": 0,
                    "max_streak": 0
                }
                
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ *Access Granted!*\n\n🆔 *Device ID:* `{device_id}`\n\n🎯 Bot will start automatically!\n\n📊 *Rules:*\n• Win → Multiplier resets to 1x\n• Loss → Next prediction 3x\n\n❌ To stop: /stop",
                    parse_mode='Markdown'
                )
                print(f"✅ Access granted for {chat_id}")
                break
        time.sleep(1)

def start(update: Update, context: CallbackContext):
    user_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    device_id = get_or_create_device_id(user_id)
    
    if user_id in users and "multiplier" in users[user_id]:
        update.message.reply_text(
            f"✅ *Bot is already active!*\n\n🆔 *Device ID:* `{device_id}`",
            parse_mode='Markdown'
        )
        return
    
    has_access = check_device_access(device_id)
    
    if has_access:
        users[user_id] = {
            "device_id": device_id,
            "multiplier": 1,
            "last_prediction": None,
            "last_sent_period": None,
            "user_wins": 0,
            "user_losses": 0,
            "win_streak": 0,
            "loss_streak": 0,
            "max_streak": 0
        }
        update.message.reply_text(
            f"✅ *Access Granted!*\n\n🆔 *Device ID:* `{device_id}`\n\n🎯 Bot will start automatically!",
            parse_mode='Markdown'
        )
    else:
        sent_msg = update.message.reply_text(
            f"🔐 *Welcome {user_name}!*\n\n"
            f"🆔 *Your Device ID:*\n`{device_id}`\n\n"
            f"⏳ *Waiting for access...*\n\n"
            f"📌 *Steps:*\n"
            f"1️⃣ Copy Device ID\n"
            f"2️⃣ Contact Admin: @INDPROPUBG\n"
            f"3️⃣ Send Device ID\n\n"
            f"✅ Bot will auto-start when access is granted!",
            parse_mode='Markdown'
        )
        
        users[user_id] = {"waiting_msg_id": sent_msg.message_id}
        threading.Thread(target=check_access_loop, args=(user_id, context), daemon=True).start()

def stop(update: Update, context: CallbackContext):
    user_id = update.effective_chat.id
    if user_id in users:
        del users[user_id]
    update.message.reply_text(
        f"❌ *Bot Stopped!*\n\nSend /start to activate again.",
        parse_mode='Markdown'
    )

# ============================================
# MAIN CYCLE - EXACT MINUTE TIMING
# ============================================

def process_cycle(context: CallbackContext):
    global last_processed_minute
    
    current_time = datetime.now()
    current_second = current_time.second
    current_minute = current_time.minute
    
    # ONLY PROCESS AT EXACT 00 SECONDS
    if current_second != 0:
        return
    
    # PREVENT DUPLICATE
    if current_minute == last_processed_minute:
        return
    
    last_processed_minute = current_minute
    
    print(f"\n{'='*70}")
    print(f"🕐 CYCLE START at {current_time.strftime('%H:%M:%S')}")
    print(f"{'='*70}")
    
    # FETCH LATEST DATA
    game_list = fetch_game_data()
    if not game_list or len(game_list) < 2:
        print("❌ No data available")
        return
    
    # CURRENT ISSUE (JUST ENDED)
    current_issue = game_list[0]['issueNumber']
    current_number = game_list[0]['number']
    current_result = classify(current_number)
    current_display = current_issue[-4:]
    
    # NEXT ISSUE
    next_issue = str(int(current_issue) + 1)
    next_display = next_issue[-4:]
    
    print(f"📊 Current Issue (Just Ended): {current_display} → Result: {current_result}")
    print(f"📊 Next Issue (To Predict): {next_display}")
    
    # PROCESS EACH USER
    for user_id in list(users.keys()):
        user_data = users[user_id]
        
        if "waiting_msg_id" in user_data:
            continue
        
        device_id = user_data["device_id"]
        
        if not check_device_access(device_id):
            if user_id in users:
                del users[user_id]
            continue
        
        # ============ STEP 1: SEND RESULT ============
        result_key = f"{user_id}_{current_issue}"
        
        if result_key not in sent_results:
            last_pred = user_data.get("last_prediction")
            last_sent_period = user_data.get("last_sent_period")
            multiplier = user_data.get("multiplier", 1)
            
            if last_sent_period == current_issue and last_pred:
                is_win = (last_pred == current_result)
                invest = 10 * multiplier
                
                if is_win:
                    user_data["multiplier"] = 1
                    user_data["user_wins"] += 1
                    caption = f"""✅ *WIN* ✅

━━━━━━━━━━━━━━━━━━━
🆔 *Period:* {current_display}
🎯 *Prediction:* {last_pred}
📊 *Result:* {current_result}

💰 *Investment:* ₹{invest}
💎 *Multiply:* {multiplier}x
🎉 *Congratulations!*

📊 *Stats:* W:{user_data['user_wins']} L:{user_data['user_losses']}"""
                else:
                    user_data["multiplier"] = multiplier * 3
                    user_data["user_losses"] += 1
                    caption = f"""❌ *LOSS* ❌

━━━━━━━━━━━━━━━━━━━
🆔 *Period:* {current_display}
🎯 *Prediction:* {last_pred}
📊 *Result:* {current_result}

💰 *Investment:* ₹{invest}
💎 *Multiply:* {multiplier}x
📈 *Next:* {user_data['multiplier']}x

*Better luck next time!*

📊 *Stats:* W:{user_data['user_wins']} L:{user_data['user_losses']}"""
                
                try:
                    if is_win and os.path.exists("win.jpg"):
                        with open("win.jpg", "rb") as img:
                            context.bot.send_photo(user_id, photo=img, caption=caption, parse_mode='Markdown')
                    elif not is_win and os.path.exists("loss.jpg"):
                        with open("loss.jpg", "rb") as img:
                            context.bot.send_photo(user_id, photo=img, caption=caption, parse_mode='Markdown')
                    else:
                        context.bot.send_message(user_id, caption, parse_mode='Markdown')
                except:
                    context.bot.send_message(user_id, caption, parse_mode='Markdown')
                
                sent_results[result_key] = True
                print(f"✅ RESULT SENT for period {current_display}")
        
        # ============ STEP 2: SEND PREDICTION ============
        prediction_key = f"{user_id}_{next_issue}"
        
        if prediction_key not in sent_predictions:
            history_numbers = [item['number'] for item in game_list[:15]]
            prediction, confidence = get_weighted_prediction(history_numbers)
            curr_mult = user_data.get("multiplier", 1)
            invest = 10 * curr_mult
            
            user_data["last_sent_period"] = next_issue
            user_data["last_prediction"] = prediction
            
            total = user_data["user_wins"] + user_data["user_losses"]
            accuracy = int((user_data["user_wins"] / total * 100)) if total > 0 else 0
            
            caption = f"""🎯 *PREDICTION*
━━━━━━━━━━━━━━━━━━━

🆔 *Period:* {next_display}
🎲 *Prediction:* *{prediction}*
📊 *Confidence:* {confidence}%

━━━━━━━━━━━━━━━━━━━
💰 *INVEST:* ₹{invest}
💎 *MULTIPLY:* {curr_mult}x
💵 *PURCHASE PRICE:* ₹{invest}

━━━━━━━━━━━━━━━━━━━
⏰ *Next result in 1 minute!*

📊 *Stats:* W:{user_data['user_wins']} L:{user_data['user_losses']} | Acc:{accuracy}%"""
            
            try:
                if prediction == "BIG" and os.path.exists("big.jpg"):
                    with open("big.jpg", "rb") as img:
                        context.bot.send_photo(user_id, photo=img, caption=caption, parse_mode='Markdown')
                elif prediction == "SMALL" and os.path.exists("small.jpg"):
                    with open("small.jpg", "rb") as img:
                        context.bot.send_photo(user_id, photo=img, caption=caption, parse_mode='Markdown')
                else:
                    context.bot.send_message(user_id, caption, parse_mode='Markdown')
            except:
                context.bot.send_message(user_id, caption, parse_mode='Markdown')
            
            sent_predictions[prediction_key] = True
            print(f"✅ PREDICTION SENT: {prediction} for period {next_display}")
    
    print(f"✅ CYCLE COMPLETE at {datetime.now().strftime('%H:%M:%S')}")

# ============================================
# CLEANUP
# ============================================

def cleanup_task(context: CallbackContext):
    global sent_results, sent_predictions
    if len(sent_results) > 200:
        sent_results = dict(list(sent_results.items())[-200:])
    if len(sent_predictions) > 200:
        sent_predictions = dict(list(sent_predictions.items())[-200:])

# ============================================
# MAIN
# ============================================

def main():
    print("=" * 70)
    print("🤖 WIN MAX BOT - PRODUCTION READY")
    print("=" * 70)
    print("✅ Device ID Access System")
    print("✅ L1-L13 Weighted Prediction Logic")
    print("✅ EXACT Minute Cycle (00 seconds)")
    print("✅ NO SPAM - 2 messages per minute")
    print("=" * 70)
    
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop))
    
    job_queue = updater.job_queue
    if job_queue:
        job_queue.run_repeating(process_cycle, interval=1, first=1)
        job_queue.run_repeating(cleanup_task, interval=3600, first=3600)
        print("✅ Timer: Checking every 1 second")
    
    print("\n🚀 Bot is running!")
    print("📱 Commands: /start, /stop")
    print("=" * 70)
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()