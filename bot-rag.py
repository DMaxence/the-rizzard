import os
import subprocess
import tempfile
import uuid
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
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

# Load environment variables
openai_api_key = os.environ.get("OPENAI_API_KEY")
telegram_api_key = os.environ.get("TELEGRAM_BOT_TOKEN")

# Adding ChatOpenAI to use langchain for the RAG system
model = ChatOpenAI(model="gpt-4o-mini")
# Instantiate OpenAI for TTS-1 and Whisper-1
client = OpenAI(api_key=openai_api_key)
# Store will keep our conversation history
store = {}

# Define the prompt template for the chatbot, including instructions for handling messages, voice, and video
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

# Create a processing chain that combines the prompt template with the model
chain = prompt | model


# Function to retrieve or initialize the chat history for a given user session
async def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = InMemoryChatMessageHistory()  # Initialize if not present
    return store[session_id]


# Function to generate a response based on user message and session history
async def generate_response(user_id, user_message) -> str:
    config = {
        "configurable": {"session_id": user_id}
    }  # Configuration including session ID
    session_history = await get_session_history(user_id)  # Retrieve session history
    with_message_history = RunnableWithMessageHistory(
        chain, lambda: session_history
    )  # Prepare to handle message history
    response = with_message_history.invoke(
        [HumanMessage(content=user_message)], config=config
    )  # Generate response
    return response.content


# Handler for /start command to initiate interaction with the chatbot
async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id  # Extract user ID
    user_message = update.message.text  # Extract user message
    response = await generate_response(
        user_id, user_message
    )  # Generate chatbot response
    await update.message.reply_text(response)  # Send response back to user


# Handler for general text messages to generate and send chatbot responses
async def handle_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id  # Extract user ID
    user_message = update.message.text  # Extract user message
    response = await generate_response(
        user_id, user_message
    )  # Generate chatbot response
    await update.message.reply_text(response)  # Send response back to user


def speech_to_text_conversion(file_path):
    # Open the audio file specified by file_path in binary read mode
    with open(file_path, "rb") as file_like:
        # Use OpenAI's Whisper-1 model to convert speech in the audio file to text
        transcription = client.audio.transcriptions.create(
            model="whisper-1", file=file_like
        )
    # Return the transcribed text from the audio file
    return transcription.text


async def text_to_speech_conversion(text) -> str:
    # Generate a unique ID for temporary file names
    unique_id = uuid.uuid4().hex
    mp3_path = f"{unique_id}.mp3"  # Path for temporary MP3 file
    ogg_path = f"{unique_id}.ogg"  # Path for final OGG file

    # Convert the input text to speech and save it as an MP3 file
    with client.audio.speech.with_streaming_response.create(
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


async def process_voice_message(update: Update, context: CallbackContext):
    user_id = update.effective_user.id  # Get the ID of the user sending the message

    # Download and save the voice message from Telegram
    file = await update.message.voice.get_file()  # Fetch the voice file
    file_bytearray = (
        await file.download_as_bytearray()
    )  # Download the file as a byte array

    # Save the byte array to a temporary OGG file
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as temp_ogg:
        temp_ogg.write(file_bytearray)  # Write byte data to the file
        temp_ogg_path = temp_ogg.name  # Get the file path

    # Convert the temporary OGG file to WAV format
    wav_path = temp_ogg_path.replace(".ogg", ".wav")
    subprocess.run(
        ["ffmpeg", "-i", temp_ogg_path, wav_path], check=True
    )  # Use ffmpeg for conversion

    # Convert the WAV file to text using speech-to-text conversion
    text = speech_to_text_conversion(wav_path)

    # Generate a response based on the text and convert it to speech
    response = await generate_response(user_id, text)
    audio_path = await text_to_speech_conversion(response)

    # Send the generated speech response as a voice message
    await send_voice_message(update, context, audio_path)


async def send_voice_message(update: Update, context: CallbackContext, audio_path: str):
    # Open the audio file and send it as a voice message
    with open(audio_path, "rb") as audio_data:
        await update.message.reply_voice(voice=audio_data)

    # Remove the OGG file from the server after sending it
    if os.path.exists(audio_path):
        os.remove(audio_path)


def main() -> None:
    # Create the Telegram bot application using the provided token
    application = ApplicationBuilder().token(telegram_api_key).build()

    # Add handler for the /start command, which triggers the 'start' function
    application.add_handler(CommandHandler("start", start))

    # Add handler for text messages (excluding commands), which triggers the 'handle_message' function
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Add handler for voice messages, which triggers the 'process_voice_message' function
    application.add_handler(MessageHandler(filters.VOICE, process_voice_message))

    # Start polling for new messages and handle them as they arrive
    application.run_polling()


if __name__ == "__main__":
    main()  # Run the main function if this script is executed directly