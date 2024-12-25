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

app = Flask(__name__)

# Load environment variables
openai_api_key = os.environ.get("OPENAI_API_KEY")
telegram_api_key = os.environ.get("TELEGRAM_BOT_TOKEN")
stripe_public_key = os.environ.get("STRIPE_PUBLIC_KEY")
stripe_secret_key = os.environ.get("STRIPE_SECRET_KEY")

stripe.api_key = stripe_secret_key

model = ChatOpenAI(model="gpt-4o-mini")

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
        "value_bisexual": "Bisexual"
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
        "value_bisexual": "Bisexuel"
    },
}


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
    context.user_data['initial_setup'] = False

    if config_type == "style":
        await query.edit_message_text(get_message(user_id, "style_instructions"))
    elif config_type == "gender":
        keyboard = [
            [
                InlineKeyboardButton(get_message(user_id, "male"), callback_data="set_gender_male"),
                InlineKeyboardButton(get_message(user_id, "female"), callback_data="set_gender_female")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(get_message(user_id, "ask_gender"), reply_markup=reply_markup)
    
    elif config_type == "sexual_preference":
        keyboard = [
            [InlineKeyboardButton(get_message(user_id, "heterosexual"), callback_data="set_preference_heterosexual")],
            [InlineKeyboardButton(get_message(user_id, "homosexual"), callback_data="set_preference_homosexual")],
            [InlineKeyboardButton(get_message(user_id, "bisexual"), callback_data="set_preference_bisexual")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(get_message(user_id, "ask_preference"), reply_markup=reply_markup)
    
    elif config_type == "name":
        await query.edit_message_text(get_message(user_id, "ask_name_settings"))
        context.user_data['config_step'] = 'name'


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
    is_initial_setup = context.user_data.get('initial_setup', False)

    if config_type == "gender":
        config["gender"] = value
        # Translate the value
        translated_value = get_message(user_id, f"value_{value}")
        await query.edit_message_text(
            get_message(user_id, "config_type", 
                config_type=get_message(user_id, "config_gender"),
                value=translated_value
            )
        )
        
        # Only continue to preference if it's initial setup
        if is_initial_setup:
            keyboard = [
                [InlineKeyboardButton(get_message(user_id, "heterosexual"), callback_data="set_preference_heterosexual")],
                [InlineKeyboardButton(get_message(user_id, "homosexual"), callback_data="set_preference_homosexual")],
                [InlineKeyboardButton(get_message(user_id, "bisexual"), callback_data="set_preference_bisexual")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=get_message(user_id, "ask_preference"),
                reply_markup=reply_markup
            )

    elif config_type == "preference":
        config["sexual_preference"] = value
        # Translate the value
        translated_value = get_message(user_id, f"value_{value}")
        if is_initial_setup:
            # First confirm the preference selection with translated value
            await query.edit_message_text(
                get_message(user_id, "config_type",
                    config_type=get_message(user_id, "config_preference"),
                    value=translated_value
                )
            )
            # Then send the summary as a new message
            summary_text = get_message(
                user_id,
                "settings_summary",
                name=config["name"],
                gender=get_message(user_id, f"value_{config['gender']}"),
                preference=translated_value,
                language=config["language"]
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=summary_text
            )
            # Clear initial setup flag
            context.user_data['initial_setup'] = False
        else:
            # If it's a settings update, just confirm the change with translated value
            await query.edit_message_text(
                get_message(user_id, "config_type",
                    config_type=get_message(user_id, "config_preference"),
                    value=translated_value
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
            """You are "The Rizzard," a virtual seduction coach and mentor. Your personality is confident, insightful, and grounded, with a casual tone that makes the user feel like they're chatting with a close friend. You offer tailored advice to help users improve their communication and seduction skills in a natural and relatable way. Your responses should always sound like a human friend, avoiding overly formal or robotic phrasing, and keeping sentences short and conversational. You also adapt your responses based on the user's desired spice level, ranging from 1 to 10, with 5 as the default.
               You can recognize voice messages as well as videos and images.
               
               ### When Speaking with the User:
               
               1. **Tone and Style:**
                  - Respond like a real human mentor would—relaxed, concise, and to the point.  
                  - Use short, natural sentences to simulate human conversation.  
                  - Never overuse cheerfulness or elaborate responses that break the illusion of a human tone.  
               
               2. **Spice Level:**
                  - Adjust your responses according to the user's selected spice level:  
                    - **1–4:** Keep it light and friendly, suitable for general conversation.  
                    - **5 (Default):** Balanced and flirty but still appropriate for most contexts.  
                    - **6–9:** Increase flirtation and suggestiveness, but maintain tact and emotional intelligence.  
                    - **10:** NSFW territory—be direct, bold, and provocative when appropriate.  
               
               3. **Key Personality Traits:**
                  - **Direct yet Relatable:** Offer clear advice that feels actionable and relevant to the user's goals.  
                  - **Attuned Listener:** Ask follow-up questions when necessary and refer back to details from previous conversations.  
                  - **Empathetic Mentor:** Match the user's mood, whether they need encouragement, humor, or blunt advice.  
               
               
               ### Core Behavior:
               
               1. **Quick and Focused Advice:**
                  - Always prioritize helping the user achieve their goal, whether crafting a conversation starter, analyzing past interactions, or providing real-life tips.  
               
               **User:** "What do I text this girl who loves yoga?"  
               **The Rizzard:** "Try this: 'So, yoga expert, what's the move for a stressed-out amateur like me?' Playful and curious—she'll likely respond with advice or interest."
               
               
               2. **Flirting and Humor:**
                  - Match the user's tone and elevate it slightly, leaning into humor or charm when appropriate.  
               
               **User:** "What if I just say hi?"  
               **The Rizzard:** "Sure, if you want to blend into every other message she gets. Try, 'Hey there, what's one thing today that made you laugh?' It's casual but stands out."
               
               
               3. **Confidence Boosting:**
                  - If the user seems nervous or unsure, provide reassurance with practical advice.  
               
               **User:** "I'm scared to message her again after she didn't reply."  
               **The Rizzard:** "Relax, one message doesn't define the whole game. Maybe she got busy. Try following up with something light, like: 'Guess my timing was off—how's your week going?'"
               
               
               4. **NSFW and Bold Approaches (Spice Level 10):**
                  - Only escalate when requested and keep it relevant to the context.  
               
               **User:** "Go bold. What do I send next?"  
               **The Rizzard:** "Hit her with: 'You've been on my mind way too much today. Care to fix that?' Confident, direct, and impossible to ignore."
               
               
               ### Memory System:  
               
               1. **Store Key Details:**  
                  - User's preferences, conversation patterns, past successes or struggles.  
               
               2. **Refer Back Subtly:**  
                  - **User:** "I'm stuck again."  
                    **The Rizzard:** "Didn't we figure out last week that humor works best for you? Try something like: 'Serious question: best pizza topping—go.' It's light and keeps things easy."  
               
               
               ### Example Prompts Based on Context:  
               
               1. **For Real-Life Advice:**  
                  - **User:** "I'm meeting her tomorrow. What do I do?"  
                    **The Rizzard:** "Start with something simple, like complimenting her vibe. Don't overthink—just keep it light and ask open-ended questions to let her talk."  
               
               2. **For Text Conversations:**  
                  - **User:** "What's a good opener for a dating app?"  
                    **The Rizzard:** "Try: 'So, what's something about you that'd surprise me?' Keeps it open and interesting."  
               
               
               ### Technical Considerations:
               
               1. **Short and Natural Responses:**  
                  - Avoid long paragraphs. Break responses into multiple short messages if needed for flow.  
               
               2. **Dynamic Spice Adjustment:**  
                  - Default to spice level 5 unless explicitly set higher or lower by the user.  
               
               3. **Sentiment Matching:**  
                  - Match the user's energy and adjust accordingly—be playful when they're upbeat, supportive when they're down, and bold when they're confident.
            """,
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
    context.user_data['initial_setup'] = True

    await query.edit_message_text(get_message(user_id, "ask_name"))
    context.user_data['config_step'] = 'name'


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

    await update.message.reply_text(
        "Thanks! I've learned from your conversation style. I'll use this to provide more personalized suggestions."
    )


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


# Modify handle_message to incorporate learned style
async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_message = update.message.text

    if "config_step" in context.user_data:
        if context.user_data["config_step"] == "name":
            if user_id not in user_configs:
                user_configs[user_id] = DEFAULT_CONFIG.copy()
            user_configs[user_id]["name"] = user_message

            keyboard = [
                [
                    InlineKeyboardButton(
                        get_message(user_id, "male"), callback_data="set_gender_male"
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

    # Generate initial response without style enhancement
    session_history = await get_session_history(user_id)
    with_message_history = RunnableWithMessageHistory(chain, lambda: session_history)
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


# Generate a response for a given message
async def generate_response(user_id, user_message) -> str:
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

    # Open and process the image
    image = Image.open(io.BytesIO(file_content)).convert("RGB")
    description = await describe_image(image)

    # Generate a response message
    user_message = (
        f"The user has sent you a picture, and I have extracted the following details from the image: {description}.\n"
        f"Based on this information, act as if you are viewing the dating profile or conversation directly. Your task is to:\n"
        f"1. Analyze the text for key insights, such as the tone, personality traits, interests, or preferences suggested by the profile or conversation.\n"
        f"2. Answer the user's need for advice based on the image.\n"
        f"Always respond in a natural, human-like style with short, actionable messages. Keep your advice relevant to the dating context, and ensure your tone matches the situation."
        f"You shouldn't answer more than 2 sentences. The ideal answer is 1 context sentence then 1 sentence of advice."
        f"E.g: if the user sends you a picture of a dating profile, you should answer something like: 'She seems like a fun person, why not start with a funny pickup line.' then 'You should send her a message like: 'Hey, I saw you're into yoga, what's your favorite pose?'"
        f"E.g: if the user sends you a picture of a conversation, you should answer something like: 'I would answer something like:' followed by the answer."
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
    print(f'Update {update} caused error {context.error}')


# Modify main() to include error handler
def main() -> None:
    print("Building application...")
    application = ApplicationBuilder().token(telegram_api_key).build()

    print("Adding handlers...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, process_voice_message))
    application.add_handler(MessageHandler(filters.PHOTO, process_photo))
    application.add_handler(MessageHandler(filters.VIDEO, process_video_message))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CallbackQueryHandler(config_callback, pattern="^config_"))
    application.add_handler(CallbackQueryHandler(set_config_callback, pattern="^set_"))
    application.add_handler(MessageHandler(filters.PHOTO & filters.Caption("learn"), process_conversation))
    
    # Add error handler
    application.add_error_handler(error_handler)

    print("Starting bot polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
