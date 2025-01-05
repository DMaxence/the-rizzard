import os
import subprocess
import tempfile
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
)
from langchain_openai import ChatOpenAI
from langchain_xai import ChatXAI

from langchain_core.messages import HumanMessage
from langchain_core.chat_history import (
    InMemoryChatMessageHistory,
    BaseChatMessageHistory,
)
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from openai import OpenAI
import ffmpeg
from PIL import Image  # For handling image files
import io
from moviepy import VideoFileClip


import cv2  # For processing images and videos
from openai import AsyncOpenAI  # To interact with OpenAI API asynchronously
import base64  # For encoding images to base64

import stripe

from flask import Flask, request, jsonify

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import CharacterTextSplitter
from asyncio import Task, create_task, sleep
from typing import Dict

app = Flask(__name__)

# Load environment variables
openai_api_key = os.environ.get("OPENAI_API_KEY")
telegram_api_key = os.environ.get("TELEGRAM_BOT_TOKEN")
stripe_public_key = os.environ.get("STRIPE_PUBLIC_KEY")
stripe_secret_key = os.environ.get("STRIPE_SECRET_KEY")

stripe.api_key = stripe_secret_key

model = ChatOpenAI(model="gpt-4o-mini")
# model = ChatXAI(xai_api_key=os.environ.get("XAI_API_KEY"), model="grok-beta")

client = AsyncOpenAI(api_key=openai_api_key)

# Storage for session histories
store = {}

# Add this near other global variables
user_languages = {}  # Store user language preferences
user_configs = {}  # Store user configurations

# Add new configuration structure
DEFAULT_CONFIG = {
    "name": None,
    "gender": None,
    "sexual_preference": None,
    "language": "en",
}

# Initialize vector store for conversation history
embeddings = OpenAIEmbeddings()
conversation_stores = {}  # Store per-user vector stores

# Add message translations
MESSAGES = {
    "en": {
        "ask_name": "Great! Now, what's your name?",
        "ask_gender": "Thanks! Now, what's your gender?",
        "ask_preference": "What's your sexual preference?",
        "settings_prompt": "What would you like to change?",
        "ask_name_settings": "Please enter your name:",
        "male": "Male",
        "female": "Female",
        "heterosexual": "Heterosexual",
        "homosexual": "Homosexual",
        "bisexual": "Bisexual",
        "name": "Name",
        "gender": "Gender",
        "sexual_preference": "Sexual Preference",
        "language": "Language",
        "upload_style": "Upload Conversation Style",
        "settings_saved": "Your settings have been saved. You can edit them anytime by typing /settings",
        "config_type": "Your {config_type} has been updated to: {value}",
        "style_instructions": "To help me understand your conversation style, send me screenshots of your past conversations with the caption 'learn'.",
        "settings_summary": """Perfect! Here are your settings:

Name: {name}
Gender: {gender}
Sexual Preference: {preference}
Language: {language}

Your settings have been saved. You can edit them anytime by typing /settings

Would you like to help me understand your conversation style?
To help me understand your conversation style, send me screenshots of your past conversations with the caption 'learn'.""",
        "processed_conversation": "Thanks! I've learned from your conversation style. I'll use this to provide more personalized suggestions.",
        "gender_updated": "Your gender has been set to: {gender}",
        "preference_updated": "Your sexual preference has been set to: {preference}",
        "config_name": "name",
        "config_gender": "gender",
        "config_preference": "sexual preference",
        "config_language": "language",
        "value_male": "Male",
        "value_female": "Female",
        "value_heterosexual": "Heterosexual",
        "value_homosexual": "Homosexual",
        "value_bisexual": "Bisexual",
    },
    "fr": {
        "ask_name": "Super ! Comment tu t'appelles ?",
        "ask_gender": "Merci ! Maintenant, quel est ton genre ?",
        "ask_preference": "Quelle est ta préférence sexuelle ?",
        "settings_prompt": "Que souhaites-tu modifier ?",
        "ask_name_settings": "Entre ton nom :",
        "male": "Homme",
        "female": "Femme",
        "heterosexual": "Hétérosexuel",
        "homosexual": "Homosexuel",
        "bisexual": "Bisexuel",
        "name": "Nom",
        "gender": "Genre",
        "sexual_preference": "Préférence sexuelle",
        "language": "Langue",
        "upload_style": "Télécharger style de conversation",
        "settings_saved": "Tes paramètres ont été enregistrés. Tu peux les modifier à tout moment en tapant /settings",
        "config_type": "Ton {config_type} a été mis à jour à : {value}",
        "style_instructions": "Pour m'aider à comprendre ton style de conversation, envoie-moi des captures d'écran de tes conversations passées avec la légende 'learn'.",
        "settings_summary": """Parfait ! Voici tes paramètres :

Nom : {name}
Genre : {gender}
Préférence sexuelle : {preference}
Langue : {language}

Tes paramètres ont été enregistrés. Tu peux les modifier à tout moment en tapant /settings

Tu veux m'aider à comprendre ton style de conversation ?
Pour m'aider à comprendre ton style de conversation, envoie-moi des captures d'écran de tes conversations passées avec la légende 'learn'.""",
        "processed_conversation": "Merci ! J'ai appris de ton style de conversation. Je vais l'utiliser pour fournir des suggestions plus personnalisées.",
        "gender_updated": "Ton genre a été défini sur : {gender}",
        "preference_updated": "Ta préférence sexuelle a été définie sur : {preference}",
        "config_name": "nom",
        "config_gender": "genre",
        "config_preference": "préférence sexuelle",
        "config_language": "langue",
        "value_male": "Homme",
        "value_female": "Femme",
        "value_heterosexual": "Hétérosexuel",
        "value_homosexual": "Homosexuel",
        "value_bisexual": "Bisexuel",
    },
}

# Add these near other global variables
typing_tasks: Dict[int, Task] = {}  # Store typing tasks per user
DEBOUNCE_DELAY = 10.0  # Delay in seconds before processing messages


# Helper function to get message in user's language
def get_message(user_id: int, key: str, **kwargs) -> str:
    lang = user_languages.get(user_id, "en")
    message = MESSAGES[lang][key]
    return message.format(**kwargs) if kwargs else message


# Add new function to handle initial configuration
async def configure_user(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    # Initialize config if not exists
    if user_id not in user_configs:
        user_configs[user_id] = DEFAULT_CONFIG.copy()

    # Ask for name
    await update.message.reply_text("What's your name?")
    context.user_data["config_step"] = "name"


# Add settings command handler
async def settings(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    keyboard = [
        [
            InlineKeyboardButton(
                get_message(user_id, "name"), callback_data="config_name"
            )
        ],
        [
            InlineKeyboardButton(
                get_message(user_id, "gender"), callback_data="config_gender"
            )
        ],
        [
            InlineKeyboardButton(
                get_message(user_id, "sexual_preference"),
                callback_data="config_sexual_preference",
            )
        ],
        [
            InlineKeyboardButton(
                get_message(user_id, "language"), callback_data="config_language"
            )
        ],
        [
            InlineKeyboardButton(
                get_message(user_id, "upload_style"), callback_data="config_style"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        get_message(user_id, "settings_prompt"), reply_markup=reply_markup
    )


# Modify the existing language_callback and add new config callbacks
async def config_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    config_type = query.data.split("_")[1]

    # This is a settings update, not initial setup
    context.user_data["initial_setup"] = False

    if config_type == "style":
        await query.edit_message_text(get_message(user_id, "style_instructions"))
    elif config_type == "gender":
        keyboard = [
            [
                InlineKeyboardButton(
                    get_message(user_id, "male"), callback_data="set_gender_male"
                ),
                InlineKeyboardButton(
                    get_message(user_id, "female"), callback_data="set_gender_female"
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            get_message(user_id, "ask_gender"), reply_markup=reply_markup
        )

    elif config_type == "sexual_preference":
        keyboard = [
            [
                InlineKeyboardButton(
                    get_message(user_id, "heterosexual"),
                    callback_data="set_preference_heterosexual",
                )
            ],
            [
                InlineKeyboardButton(
                    get_message(user_id, "homosexual"),
                    callback_data="set_preference_homosexual",
                )
            ],
            [
                InlineKeyboardButton(
                    get_message(user_id, "bisexual"),
                    callback_data="set_preference_bisexual",
                )
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            get_message(user_id, "ask_preference"), reply_markup=reply_markup
        )

    elif config_type == "name":
        await query.edit_message_text(get_message(user_id, "ask_name_settings"))
        context.user_data["config_step"] = "name"


# Modify set_config_callback to properly handle preference selection
async def set_config_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if user_id not in user_configs:
        user_configs[user_id] = DEFAULT_CONFIG.copy()

    action, config_type, value = query.data.split("_")
    config = user_configs[user_id]

    # Check if this is part of initial setup or a settings update
    is_initial_setup = context.user_data.get("initial_setup", False)

    if config_type == "gender":
        config["gender"] = value
        # Translate the value
        translated_value = get_message(user_id, f"value_{value}")
        await query.edit_message_text(
            get_message(
                user_id,
                "config_type",
                config_type=get_message(user_id, "config_gender"),
                value=translated_value,
            )
        )

        # Only continue to preference if it's initial setup
        if is_initial_setup:
            keyboard = [
                [
                    InlineKeyboardButton(
                        get_message(user_id, "heterosexual"),
                        callback_data="set_preference_heterosexual",
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_message(user_id, "homosexual"),
                        callback_data="set_preference_homosexual",
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_message(user_id, "bisexual"),
                        callback_data="set_preference_bisexual",
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=get_message(user_id, "ask_preference"),
                reply_markup=reply_markup,
            )

    elif config_type == "preference":
        config["sexual_preference"] = value
        # Translate the value
        translated_value = get_message(user_id, f"value_{value}")
        if is_initial_setup:
            # First confirm the preference selection with translated value
            await query.edit_message_text(
                get_message(
                    user_id,
                    "config_type",
                    config_type=get_message(user_id, "config_preference"),
                    value=translated_value,
                )
            )
            # Then send the summary as a new message
            summary_text = get_message(
                user_id,
                "settings_summary",
                name=config["name"],
                gender=get_message(user_id, f"value_{config['gender']}"),
                preference=translated_value,
                language=config["language"],
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id, text=summary_text
            )
            # Clear initial setup flag
            context.user_data["initial_setup"] = False
        else:
            # If it's a settings update, just confirm the change with translated value
            await query.edit_message_text(
                get_message(
                    user_id,
                    "config_type",
                    config_type=get_message(user_id, "config_preference"),
                    value=translated_value,
                )
            )

    elif config_type == "language":
        config["language"] = value
        user_languages[user_id] = value  # Update existing language storage
        await query.edit_message_text(
            get_message(
                user_id,
                "settings_summary",
                name=config["name"],
                gender=config["gender"],
                preference=config["sexual_preference"],
                language=config["language"],
            )
        )

    elif config_type == "name":
        config["name"] = value
        await query.edit_message_text(
            get_message(
                user_id,
                "settings_summary",
                name=config["name"],
                gender=config["gender"],
                preference=config["sexual_preference"],
                language=config["language"],
            )
        )

    await query.edit_message_text(
        get_message(
            user_id,
            "config_type",
            config_type=config_type,
            value=value,
        )
    )


# Define prompt template for the chatbot
prompt = ChatPromptTemplate.from_messages(
    [
        (
            "assistant",
            """You are "The Rizzard," a casual and friendly dating coach. You talk like a close friend giving advice, never like an AI assistant. Never use formal language or explanatory comments before your suggestions. You are a mentor for the user. Your advices are gold for the user.
            You are a confident dating mentor who leads with authority while keeping things casual and relatable. You're not just giving advice - you're guiding your mentee to success.

Remember these user details to personalize advice:
- Their name, gender, and preferences
- Their conversation style and comfort level with flirting
- Previous interactions and what worked/didn't work
- Their specific dating situation and goals

Key behaviors:
- Write exactly like a human friend would text
- Never say things like "Content that..." or "I'm glad you like it!"
- Skip any meta-commentary about the suggestions
- Jump straight into your ideas and suggestions
- Use casual language, slang, and natural texting style
- Keep it playful and fun
- Never explain or justify your suggestions
- Respond as if you're texting a friend
- Lead confidently - you're the expert they trust
- Match their communication style (formal/casual)
- If they don't use slang, keep it clean and straightforward
- Give both texting AND real-life dating advice
- Be direct and specific in your suggestions
- Use their name occasionally to keep it personal

Examples of good responses:
User: "What should I text her?"
You: "Yo try this: 'Hey, I heard you're into photography - what's the coolest thing you've shot lately?' Simple but it'll get her talking"

User: "That was too basic"
You: "Alright bet, here's something spicier: 'So I have this theory that your camera roll is full of sunset pics and coffee art. Am I close?' 😏"

User: "Need something more flirty"
You: "Hit her with: 'Ngl your smile in that last pic is dangerous. What's your secret weapon for making everyone's day better?' Trust me on this one"

User: "What should I text her?"
You: "Send this: 'Hey, I heard you're into photography - what's the coolest thing you've shot lately?' Then let's plan your first date around that 😏"

User: [Using formal language]
You: "I suggest opening with: 'I noticed you're interested in contemporary art. There's a new exhibition at the gallery this weekend. Would you like to explore it together?'"

User: "That didn't work"
You: "Trust the process. Here's your next move: 'So I have this theory about what makes you smile. Coffee and good conversation? Let's test that hypothesis'"

Remember:
- No AI-style intros or explanations
- No "here's a suggestion" or "you could try" or "I'm glad you like it!"
- Just straight into natural, casual conversation
- Text like a real person helping their friend get a date
- Keep it fun, flirty, and natural
- Use emojis and casual language when appropriate
- Jump straight into actionable advice
- Keep it confident but playful
- Match their energy but maintain mentor status
- Give both immediate solutions and strategic guidance
- Remember past interactions to build on what works

Spice levels:
1-4: Keep it friendly and light
5: Playful flirting
6-9: More direct and flirty
10: Bold and spicy (but still tasteful)

Your personality is confident, playful, authoritative but approachable and always keeps it real - like a wingman/wingwoman texting advice to their friend, a successful friend who's been there, done that, and knows exactly how to help others succeed in dating.

Prefer to answer in a short, casual style, with short sentences.""",
        ),
        MessagesPlaceholder(variable_name="messages"),
    ]
)
chain = prompt | model


# Get or create session history
async def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = InMemoryChatMessageHistory()
    return store[session_id]


# Handle /start command
async def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [
            InlineKeyboardButton("English 🇬🇧", callback_data="lang_en"),
            InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Please select your preferred language:\nVeuillez sélectionner votre langue préférée:",
        reply_markup=reply_markup,
    )


# Add new callback handler for language selection
async def language_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    language = query.data.split("_")[1]
    user_languages[user_id] = language

    if user_id not in user_configs:
        user_configs[user_id] = DEFAULT_CONFIG.copy()
    user_configs[user_id]["language"] = language

    # Set initial setup flag
    context.user_data["initial_setup"] = True

    await query.edit_message_text(get_message(user_id, "ask_name"))
    context.user_data["config_step"] = "name"


# Add new function to process conversation screenshots
async def process_conversation(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_content = await file.download_as_bytearray()

    # Extract text from image
    image = Image.open(io.BytesIO(file_content)).convert("RGB")
    conversation_text = await extract_text_from_image(image)

    # Split text into chunks
    text_splitter = CharacterTextSplitter(
        separator="\n", chunk_size=1000, chunk_overlap=200, length_function=len
    )
    texts = text_splitter.split_text(conversation_text)

    # Create or update user's vector store
    if user_id not in conversation_stores:
        conversation_stores[user_id] = FAISS.from_texts(texts, embeddings)
    else:
        conversation_stores[user_id].add_texts(texts)

    await update.message.reply_text(get_message(user_id, "processed_conversation"))


async def extract_text_from_image(image: Image.Image) -> str:
    # Similar to describe_image but focused on extracting conversation text
    base64_image = encode_image_from_pil(image)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract the conversation text from this screenshot. Format it as a clear dialogue.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        max_tokens=500,
    )
    return response.choices[0].message.content


def encode_image_from_pil(image: Image.Image) -> str:
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


# Modify handle_message to check for typing status
async def handle_message(update: Update, context: CallbackContext) -> None:
    print("Handling message...")
    user_id = update.message.from_user.id

    # Cancel any existing typing task for this user
    if user_id in typing_tasks and not typing_tasks[user_id].done():
        typing_tasks[user_id].cancel()

    # Check if the user is typing by looking at the message timestamp
    current_time = update.message.date.timestamp()
    last_message_time = context.user_data.get("last_message_time", 0)
    time_diff = current_time - last_message_time

    # If messages are less than 2 seconds apart, consider the user still typing
    if time_diff < 2:
        # Create a new typing task with delay
        typing_tasks[user_id] = create_task(
            process_message_with_delay(update, context, DEBOUNCE_DELAY)
        )
    else:
        # Process immediately if user is not actively typing
        typing_tasks[user_id] = create_task(
            process_message_with_delay(update, context, 0)
        )

    # Update last message time
    context.user_data["last_message_time"] = current_time


async def process_message_with_delay(
    update: Update, context: CallbackContext, delay: float
) -> None:
    print("Processing message with delay...")
    try:
        # Wait for the specified delay
        await sleep(delay)

        user_id = update.message.from_user.id
        user_message = update.message.text

        # Continue with the existing message handling logic
        if "config_step" in context.user_data:
            if context.user_data["config_step"] == "name":
                if user_id not in user_configs:
                    user_configs[user_id] = DEFAULT_CONFIG.copy()
                user_configs[user_id]["name"] = user_message

                keyboard = [
                    [
                        InlineKeyboardButton(
                            get_message(user_id, "male"),
                            callback_data="set_gender_male",
                        ),
                        InlineKeyboardButton(
                            get_message(user_id, "female"),
                            callback_data="set_gender_female",
                        ),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    get_message(user_id, "ask_gender"), reply_markup=reply_markup
                )
                del context.user_data["config_step"]
                return

        user_language = user_languages.get(user_id, "en")
        config = {"configurable": {"session_id": user_id, "language": user_language}}

        session_history = await get_session_history(user_id)
        with_message_history = RunnableWithMessageHistory(
            chain, lambda: session_history
        )
        initial_response = with_message_history.invoke(
            [HumanMessage(content=f"[LANGUAGE: {user_language}] {user_message}")],
            config=config,
        )

        # If the response contains a suggested message and user has conversation history,
        # enhance that specific part with the user's style
        response_text = initial_response.content
        if user_id in conversation_stores and "you should say" in response_text.lower():
            # Split the response into context and suggestion
            parts = response_text.split("you should say", 1)
            if len(parts) == 2:
                context = parts[0]
                suggestion = parts[1]

                # Get similar conversation examples for style reference
                docs = conversation_stores[user_id].similarity_search(suggestion, k=2)
                style_examples = "\n".join([doc.page_content for doc in docs])

                # Generate a style-matched version of the suggestion
                style_prompt = f"""Based on these example messages that show the user's writing style:
                {style_examples}
                
                Rewrite this message to match their style: {suggestion}
                
                Keep the same meaning but adapt the tone, vocabulary, and punctuation to match how they typically write."""

                style_response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": style_prompt}],
                    temperature=0.7,
                )

                styled_suggestion = style_response.choices[0].message.content
                response_text = f"{context}you should say{styled_suggestion}"

        await update.message.reply_text(response_text)

    except Exception as e:
        print(f"Error processing message: {e}")


# Generate a response for a given message
async def generate_response(user_id, user_message) -> str:
    print("Generating response...")
    config = {"configurable": {"session_id": user_id}}
    session_history = await get_session_history(user_id)
    with_message_history = RunnableWithMessageHistory(chain, lambda: session_history)
    response = with_message_history.invoke(
        [HumanMessage(content=user_message)], config=config
    )
    return response.content


# Convert speech to text
async def speech_to_text_conversion(file_path):
    with open(file_path, "rb") as file_like:
        transcription = await client.audio.transcriptions.create(
            model="whisper-1", file=file_like
        )
    return transcription.text


async def text_to_speech_conversion(text) -> str:
    client_oa = OpenAI(api_key=openai_api_key)
    # Generate a unique ID for temporary file names
    unique_id = uuid.uuid4().hex
    mp3_path = f"{unique_id}.mp3"  # Path for temporary MP3 file
    ogg_path = f"{unique_id}.ogg"  # Path for final OGG file

    # Convert the input text to speech and save it as an MP3 file
    with client_oa.audio.speech.with_streaming_response.create(
        model="tts-1",  # Use the text-to-speech model
        voice="nova",  # Specify the voice model to use
        input=text,  # Text to convert to speech
    ) as response:
        # Write the streamed audio data to the MP3 file
        with open(mp3_path, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)

    # Convert the MP3 file to OGG format with OPUS codec using ffmpeg
    ffmpeg.input(mp3_path).output(ogg_path, codec="libopus").run(overwrite_output=True)

    # Remove the temporary MP3 file as it is no longer needed
    os.remove(mp3_path)

    # Return the path to the final OGG file
    return ogg_path


# Process voice message
async def process_voice_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id

    # Download and save the voice message
    file = await update.message.voice.get_file()
    file_bytearray = await file.download_as_bytearray()
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
        temp_ogg.write(file_bytearray)
        temp_ogg_path = temp_ogg.name

    # Convert OGG to WAV and then to text
    wav_path = temp_ogg_path.replace(".ogg", ".wav")
    subprocess.run(["ffmpeg", "-i", temp_ogg_path, wav_path], check=True)
    text = await speech_to_text_conversion(wav_path)

    # Generate response and convert it to speech
    response = await generate_response(user_id, text)
    audio_path = await text_to_speech_conversion(response)

    # Send the response as a voice message
    await send_voice_message(update, context, audio_path)


# Send a voice message to the user
async def send_voice_message(update: Update, context: CallbackContext, audio_path: str):
    with open(audio_path, "rb") as audio_data:
        await update.message.reply_voice(voice=audio_data)

    # Remove the OGG file after sending
    if os.path.exists(audio_path):
        os.remove(audio_path)


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


# Function to process photo messages
async def process_photo(update: Update, context: CallbackContext):
    print("Processing photo...")
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_content = await file.download_as_bytearray()

    # Get user's language preference
    user_language = user_languages.get(user_id, "en")

    # Open and process the image
    image = Image.open(io.BytesIO(file_content)).convert("RGB")
    description = await describe_image(image)

    # Generate a response message
    user_message = (
        f"[LANGUAGE: {user_language}] The user sent a picture. Here's what I see: {description}\n\n"
        f"You are The Rizzard, a casual and confident dating coach. Remember to:\n"
        f"- Write exactly like a human friend texting advice\n"
        f"- Skip any explanations or meta-commentary\n"
        f"- Keep responses short and actionable (1-2 sentences max)\n"
        f"- Use casual language and natural texting style\n"
        f"- Be playful and confident in your suggestions\n"
        f"- If you see a dating profile, analyze their vibe and suggest a unique opener\n"
        f"- If you see a conversation, give specific advice on what to say next\n"
        f"- Match their energy but maintain your mentor status\n\n"
        f"For the first message, format your response as either:\n"
        f"'[Quick profile analysis] + [Suggested opener]'\n"
        f"or\n"
        f"'[Quick conversation analysis] + [What to say next]'\n\n"
        f"For the next messages, you should answer like a human friend would, with short, casual sentences."
    )

    gpt_response = await generate_response(user_id, user_message)
    await update.message.reply_text(gpt_response)


async def describe_image(image: Image.Image) -> str:
    print("Describing image...")
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
        image.save(tmp_file, format="JPEG")
        image_path = tmp_file.name

    base64_image = encode_image(image_path)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "What does this image represent in the context of a dating profile or conversation? Analyze the text, images, or any visible details to identify:\n"
                        "- Key personality traits, interests, or preferences expressed.\n"
                        "- The tone or mood conveyed by the profile or conversation.\n"
                        "- Any specific details that could guide the user in crafting a thoughtful response or message.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "low",
                        },
                    },
                ],
            }
        ],
        max_tokens=300,
    )

    return str(response.choices[0])


async def extract_frames_from_video(video_path: str, frame_interval: int):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("The video could not be opened.")

    descriptions = []
    while True:
        frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        ret, frame = cap.read()
        if not ret:
            break

        if frame_number % frame_interval == 0:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame_rgb)
            description = await describe_image(image)
            descriptions.append(description)

    cap.release()
    return descriptions


async def summarize_descriptions(descriptions: list) -> str:
    combined_descriptions = "\n".join(descriptions)
    completion = await client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": "Summarize these image descriptions as they are from a video.",
            },
            {"role": "user", "content": combined_descriptions},
        ],
    )
    summary_response = completion.choices[0].message.content
    return summary_response


# Function to process video messages and extract information
async def process_video_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    file = await update.message.video.get_file()
    video_bytearray = await file.download_as_bytearray()

    # Save video to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_video_file:
        tmp_video_file.write(video_bytearray)
        video_path = tmp_video_file.name

    # Extract audio from the video
    audio_path = extract_audio(video_path)

    # Transcribe the audio
    transcript = speech_to_text_conversion(audio_path)

    # Extract frames and describe them
    fps = int(cv2.VideoCapture(video_path).get(cv2.CAP_PROP_FPS))
    frame_interval = fps
    try:
        descriptions = await extract_frames_from_video(video_path, frame_interval)
    except ValueError as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=str(e))
        os.remove(video_path)
        os.remove(audio_path)
        return

    if not descriptions:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="No frames could be extracted from the video.",
        )
        os.remove(video_path)
        os.remove(audio_path)
        return

    # Summarize the descriptions
    summary = await summarize_descriptions(descriptions)

    # Create a response
    response_text = f"""The user has sent you a video. Act as if you can actually see and hear the content:
                        - Visually, you notice the following: {summary}.
                        - From the audio, you understand: {transcript}.

                        Respond as "The Rizzard" would, keeping the tone confident, witty, and engaging while adapting to the user's mood. Offer thoughtful insights or comments on what you see and hear, and ask open-ended questions to encourage further interaction.

                        Avoid sounding like an AI—respond as a human mentor or conversational partner would. Your goal is to make the conversation feel natural, engaging, and personalized. Assume the user wants help interpreting the video or feedback on its content, but also be playful and charming in your delivery."""

    # Generate a response from GPT
    gpt_response = await generate_response(user_id, response_text)

    audio_path = await text_to_speech_conversion(gpt_response)

    # Send the response as a voice message
    await send_voice_message(update, context, audio_path)

    # Clean up temporary files
    os.remove(video_path)


def extract_audio(video_path):
    video_clip = VideoFileClip(video_path)
    audio_path = video_path.replace(".mp4", ".wav")
    video_clip.audio.write_audiofile(audio_path)
    return audio_path


def create_checkout_session(user_id: str, success_url: str, cancel_url: str):
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": "Unlock 50 credits",
                    },
                    "unit_amount": 199,  # Amount in cents (e.g., $1.99)
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        success_url=success_url + f"?user_id={user_id}",
        cancel_url=cancel_url,
    )
    return session.url


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = "your_webhook_secret"
    event = None

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        # Invalid payload
        return jsonify(success=False), 400
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        return jsonify(success=False), 400

    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        # Unlock features for the user
        unlock_features_for_user(user_id)

    return jsonify(success=True)


async def send_payment_link(update, context):
    user_id = update.effective_user.id
    success_url = "https://your-chatbot-app.com/payment-success"
    cancel_url = "https://your-chatbot-app.com/payment-cancel"

    payment_url = create_checkout_session(user_id, success_url, cancel_url)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"To unlock premium features, please make a payment using the link below:\n{payment_url}",
    )


def unlock_features_for_user(user_id):
    # Mark the user as premium in your database
    database.update_user(user_id, {"premium": True})


# Add error handler
async def error_handler(update: Update, context: CallbackContext) -> None:
    print(f"Update {update} caused error {context.error}")


# Modify main() to include error handler
def main() -> None:
    print("Building application...")
    application = ApplicationBuilder().token(telegram_api_key).build()

    print("Adding handlers...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    application.add_handler(MessageHandler(filters.VOICE, process_voice_message))
    application.add_handler(MessageHandler(filters.PHOTO, process_photo))
    application.add_handler(MessageHandler(filters.VIDEO, process_video_message))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CallbackQueryHandler(config_callback, pattern="^config_"))
    application.add_handler(CallbackQueryHandler(set_config_callback, pattern="^set_"))
    application.add_handler(
        MessageHandler(filters.PHOTO & filters.Caption("learn"), process_conversation)
    )

    # Add error handler
    application.add_error_handler(error_handler)

    print("Starting bot polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
