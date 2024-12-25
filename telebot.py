import os
import telebot 

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start', 'hello']) 
def send_welcome(message): bot.reply_to(message, "Hi there. What’s happening?")

@bot.message_handler(func=lambda msg: True)
def echo_all(message): bot.reply_to(message, message.text)

bot.infinity_polling()