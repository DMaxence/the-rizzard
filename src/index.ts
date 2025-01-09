import { UpstashRedisChatMessageHistory } from "@langchain/community/stores/message/upstash_redis";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import {
  ChatPromptTemplate,
  MessagesPlaceholder,
} from "@langchain/core/prompts";
import { RunnableWithMessageHistory } from "@langchain/core/runnables";
import { ChatOpenAI } from "@langchain/openai";
import { CharacterTextSplitter } from "@langchain/textsplitters";
import { Redis } from "@upstash/redis";
import { OpenAIEmbeddings } from "langchain/embeddings/openai";
import { OpenAI } from "openai";
import Stripe from "stripe";
import { Context, Telegraf } from "telegraf";
import { InlineKeyboardMarkup } from "telegraf/types";
import { LogSnag } from "@logsnag/node";
// import { FaissStore } from "@langchain/community/vectorstores/faiss";

import { DEFAULT_CONFIG, PROMPT } from "./config";
import { MESSAGES } from "./constants";
import { UserConfig } from "./types";
import express from "express";

// Load environment variables
const openaiApiKey = process.env.OPENAI_API_KEY;
const telegramApiKey = process.env.TELEGRAM_BOT_TOKEN;
const stripePublicKey = process.env.STRIPE_PUBLIC_KEY;
const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
const logsnagToken = process.env.LOGSNAG_TOKEN;

if (
  !openaiApiKey ||
  !telegramApiKey ||
  !stripePublicKey ||
  !stripeSecretKey ||
  !logsnagToken
) {
  throw new Error("Missing required environment variables");
}

// Initialize Stripe
const stripe = new Stripe(stripeSecretKey, { apiVersion: "2022-11-15" });

// Initialize OpenAI
const model = new ChatOpenAI({ modelName: "gpt-4o-mini" });
const client = new OpenAI({ apiKey: openaiApiKey });

// Initialize Redis client (after other initializations)
const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL!,
  token: process.env.UPSTASH_REDIS_REST_TOKEN!,
});

// Initialize vector store for conversation history
const embeddings = new OpenAIEmbeddings();
const conversationStores: Record<number, any> = {};

// Store typing tasks per user
const typingTasks: Record<number, NodeJS.Timeout> = {};
const DEBOUNCE_DELAY = 1; // 10 seconds in milliseconds

// Define prompt template for the chatbot
const prompt = ChatPromptTemplate.fromMessages([
  ["system", PROMPT],
  new MessagesPlaceholder("history"),
  ["human", "{question}"],
]);

const chain = prompt.pipe(model);

// Create global RunnableWithMessageHistory
const chainWithHistory = new RunnableWithMessageHistory({
  runnable: chain,
  getMessageHistory: (sessionId: string) =>
    new UpstashRedisChatMessageHistory({
      sessionId,
      config: {
        url: process.env.UPSTASH_REDIS_REST_URL,
        token: process.env.UPSTASH_REDIS_REST_TOKEN,
      },
    }),
  inputMessagesKey: "question",
  historyMessagesKey: "history",
});

// Add Redis helper functions
async function getUserConfig(userId: number): Promise<UserConfig | null> {
  const config = await redis.get(`user:${userId}:config`);
  return config
    ? typeof config === "string"
      ? JSON.parse(config)
      : config
    : null;
}

async function setUserConfig(
  userId: number,
  config: Partial<UserConfig>
): Promise<void> {
  const currentConfig = (await getUserConfig(userId)) || { ...DEFAULT_CONFIG };
  const newConfig = {
    ...currentConfig,
    ...config,
  };
  await redis.set(`user:${userId}:config`, JSON.stringify(newConfig));
}

async function getUserLanguage(userId: number): Promise<string> {
  try {
    const config = await getUserConfig(userId);
    return (config?.language as string) || "en";
  } catch (error) {
    console.error("Redis error getting language:", error);
    return "en"; // Fallback to English
  }
}

// Update the configureUser function to be async
const configureUser = async (
  userId: number,
  config: Partial<UserConfig>
): Promise<void> => {
  await setUserConfig(userId, config);
};

// Update getMessage function to be async
async function getMessage(
  userId: number,
  key: string,
  params: Record<string, string> = {}
): Promise<string> {
  const lang = await getUserLanguage(userId);

  let message = MESSAGES[lang]?.[key] || MESSAGES["en"][key];

  Object.entries(params).forEach(([key, value]) => {
    message = message.replace(`{${key}}`, value);
  });

  return message;
}

const bot = new Telegraf(telegramApiKey);

// Initialize LogSnag
const logsnag = new LogSnag({
  token: logsnagToken,
  project: "the-rizzard",
});

// Add start command handler
bot.command("start", async (ctx) => {
  const userId = ctx.from.id;
  console.log("Start command received for user:", userId);

  // Check if user already exists
  const existingConfig = await getUserConfig(userId);
  if (existingConfig) {
    await ctx.reply(
      await getMessage(userId, "welcomeBack", {
        name: ctx.from.first_name,
      })
    );
    await logsnag.identify({
      user_id: userId.toString(),
      properties: {
        username: ctx.from.username || "someone",
        platform: "telegram",
      },
    });
    return;
  }

  // Track new user with LogSnag
  await logsnag.track({
    channel: "users",
    event: "New User",
    description: `${ctx.from.first_name} (${
      ctx.from.username || "someone"
    }) started using The Rizzard`,
    icon: "👤",
    tags: {
      username: ctx.from.username || "someone",
      platform: "telegram",
      language: ctx.from.language_code || "unknown",
    },
  });
  console.log("LogSnag track event sent for user:", userId);

  // Set initial configuration step
  await setConfigurationStep(userId, "language");
  console.log("Set initial config step to language for user:", userId);

  await configureUser(userId, { name: ctx.from.first_name });

  // Show language selection keyboard
  const languageKeyboard: InlineKeyboardMarkup = {
    inline_keyboard: [
      [
        { text: "English 🇬🇧", callback_data: "set_language_en" },
        { text: "Français 🇫🇷", callback_data: "set_language_fr" },
      ],
    ],
  };

  await ctx.reply(
    "Please select your preferred language:\nVeuillez sélectionner votre langue préférée:",
    {
      reply_markup: languageKeyboard,
    }
  );
});

bot.command("settings", async (ctx) => {
  const userId = ctx.from.id;
  const keyboard: InlineKeyboardMarkup = {
    inline_keyboard: [
      [
        {
          text: await getMessage(userId, "name"),
          callback_data: "config_name",
        },
      ],
      [
        {
          text: await getMessage(userId, "gender"),
          callback_data: "config_gender",
        },
      ],
      [
        {
          text: await getMessage(userId, "sexualPreference"),
          callback_data: "config_sexual_preference",
        },
      ],
      [
        {
          text: await getMessage(userId, "language"),
          callback_data: "config_language",
        },
      ],
      [
        {
          text: await getMessage(userId, "uploadStyle"),
          callback_data: "config_style",
        },
      ],
    ],
  };

  await ctx.reply(await getMessage(userId, "settingsPrompt"), {
    reply_markup: keyboard,
  });
});

bot.action(/^config_(.+)$/, async (ctx) => {
  if (!ctx.callbackQuery || !("data" in ctx.callbackQuery) || !ctx.from) {
    return;
  }

  const userId = ctx.from.id;
  const configType = ctx.callbackQuery.data.split("_")[1];

  let keyboard: InlineKeyboardMarkup;

  switch (configType) {
    case "gender":
      keyboard = {
        inline_keyboard: [
          [
            {
              text: await getMessage(userId, "male"),
              callback_data: "set_gender_male",
            },
            {
              text: await getMessage(userId, "female"),
              callback_data: "set_gender_female",
            },
          ],
        ],
      };
      await ctx.editMessageText(await getMessage(userId, "askGender"), {
        reply_markup: keyboard,
      });
      break;

    case "sexual":
      keyboard = {
        inline_keyboard: [
          [
            {
              text: await getMessage(userId, "heterosexual"),
              callback_data: "set_preference_heterosexual",
            },
            {
              text: await getMessage(userId, "homosexual"),
              callback_data: "set_preference_homosexual",
            },
          ],
          [
            {
              text: await getMessage(userId, "bisexual"),
              callback_data: "set_preference_bisexual",
            },
          ],
        ],
      };
      await ctx.editMessageText(await getMessage(userId, "askPreference"), {
        reply_markup: keyboard,
      });
      break;

    case "language":
      keyboard = {
        inline_keyboard: [
          [
            { text: "English 🇬🇧", callback_data: "set_language_en" },
            { text: "Français 🇫🇷", callback_data: "set_language_fr" },
          ],
        ],
      };
      await ctx.editMessageText(await getMessage(userId, "language"), {
        reply_markup: keyboard,
      });
      break;

    case "name":
      await ctx.editMessageText(await getMessage(userId, "askNameSettings"));
      // Set user state to await name input using Redis
      await setUserAwaitingInput(userId, "name");
      break;

    case "style":
      await ctx.editMessageText(await getMessage(userId, "styleInstructions"));
      break;
  }
});

// Add Redis helper functions for temporary states
async function setUserAwaitingInput(
  userId: number,
  inputType: string
): Promise<void> {
  await redis.set(`user:${userId}:awaiting_input`, inputType);
}

async function getUserAwaitingInput(userId: number): Promise<string | null> {
  return redis.get(`user:${userId}:awaiting_input`) as Promise<string | null>;
}

async function clearUserAwaitingInput(userId: number): Promise<void> {
  await redis.del(`user:${userId}:awaiting_input`);
}

// Modify the language callback handler to handle both initial setup and settings changes
bot.action(/^set_language_(.+)$/, async (ctx) => {
  if (!ctx.callbackQuery || !("data" in ctx.callbackQuery) || !ctx.from) return;

  const userId = ctx.from.id;
  const language = ctx.callbackQuery.data.split("_")[2];

  // Get current configuration step
  const configStep = await getConfigurationStep(userId);

  // Store language in Redis
  await setUserConfig(userId, { language });

  // Add configuration message to chat history
  await chainWithHistory.invoke(
    {
      question: new SystemMessage(
        `[CONFIG UPDATE] User has changed their language preference to ${language}. Please respond in ${language} from now on.`
      ),
      language,
    },
    {
      configurable: {
        sessionId: userId.toString(),
        language,
      },
    }
  );

  // If we're in the initial configuration flow
  if (configStep === "language") {
    console.log("Moving to name step for user:", userId);
    // Move to name step
    await setConfigurationStep(userId, "name");
    // Ask for name
    await ctx.editMessageText(await getMessage(userId, "askName"));
  } else {
    // Handle as a settings change
    await ctx.editMessageText(
      await getMessage(userId, "configType", {
        config_type: await getMessage(userId, "language"),
        value: language.toUpperCase(),
      })
    );
  }
});

// Update gender callback handler
bot.action(/^set_gender_(.+)$/, async (ctx) => {
  if (!ctx.callbackQuery || !("data" in ctx.callbackQuery) || !ctx.from) return;

  const userId = ctx.from.id;
  const gender = ctx.callbackQuery.data.split("_")[2];
  const configStep = await getConfigurationStep(userId);

  // Store in Redis for UI/system purposes
  await setUserConfig(userId, { gender });

  // Add configuration message to chat history
  await chainWithHistory.invoke(
    {
      question: new SystemMessage(
        `[CONFIG UPDATE] User has identified as ${gender}. Please consider this in future interactions.`
      ),
      language: await getUserLanguage(userId),
    },
    {
      configurable: {
        sessionId: userId.toString(),
      },
    }
  );

  // If we're in the configuration flow, move to preference step
  if (configStep) {
    await setConfigurationStep(userId, "preference");

    const preferenceKeyboard: InlineKeyboardMarkup = {
      inline_keyboard: [
        [
          {
            text: await getMessage(userId, "heterosexual"),
            callback_data: "set_preference_heterosexual",
          },
          {
            text: await getMessage(userId, "homosexual"),
            callback_data: "set_preference_homosexual",
          },
        ],
        [
          {
            text: await getMessage(userId, "bisexual"),
            callback_data: "set_preference_bisexual",
          },
        ],
      ],
    };

    await ctx.editMessageText(await getMessage(userId, "askPreference"), {
      reply_markup: preferenceKeyboard,
    });
  } else {
    // Settings change flow
    await ctx.editMessageText(
      await getMessage(userId, "genderUpdated", {
        gender: await getMessage(userId, gender),
      })
    );
  }
});

// Update preference callback handler
bot.action(/^set_preference_(.+)$/, async (ctx) => {
  if (!ctx.callbackQuery || !("data" in ctx.callbackQuery) || !ctx.from) return;

  const userId = ctx.from.id;
  const preference = ctx.callbackQuery.data.split("_")[2];
  const configStep = await getConfigurationStep(userId);

  // Store in Redis for UI/system purposes
  await setUserConfig(userId, { sexual_preference: preference });

  // Add configuration message to chat history
  await chainWithHistory.invoke(
    {
      question: new SystemMessage(
        `[CONFIG UPDATE] User has set their sexual preference to ${preference}. Please consider this in future interactions and suggestions.`
      ),
      language: await getUserLanguage(userId),
    },
    {
      configurable: {
        sessionId: userId.toString(),
      },
    }
  );

  // If we're in the configuration flow, complete setup
  if (configStep) {
    // Clear configuration step to indicate completion
    await setConfigurationStep(userId, null);

    // Show configuration summary
    const config = await getUserConfig(userId);
    // const summary = [
    //   await getMessage(userId, "configSummaryTitle"),
    //   `${await getMessage(userId, "name")}: ${config?.name}`,
    //   `${await getMessage(
    //     userId,
    //     "language"
    //   )}: ${config?.language.toUpperCase()}`,
    //   `${await getMessage(userId, "gender")}: ${await getMessage(
    //     userId,
    //     config?.gender || "unknown"
    //   )}`,
    //   `${await getMessage(userId, "sexualPreference")}: ${await getMessage(
    //     userId,
    //     config?.sexual_preference || "unknown"
    //   )}`,
    // ].join("\n");

    // await ctx.editMessageText(summary);
    await ctx.reply(
      await getMessage(userId, "settingsSummary", {
        name: config?.name || "??",
        gender: await getMessage(userId, config?.gender || "??"),
        preference: await getMessage(userId, config?.sexual_preference || "??"),
        language: config?.language || "??",
      })
    );
  } else {
    // Settings change flow
    await ctx.editMessageText(
      await getMessage(userId, "preferenceUpdated", {
        preference: await getMessage(userId, preference),
      })
    );
  }
});

// Add helper function for image processing
const extractTextFromImage = async (image: Buffer): Promise<string> => {
  console.log("extractTextFromImage");
  const base64Image = image.toString("base64");

  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text: `Extract the conversation text from this screenshot. Format it as a clear dialogue. Only keep right side texts. Only keep texts with same color background from right side. Don't add names or other information.`,
          },
          {
            type: "image_url",
            image_url: {
              url: `data:image/jpeg;base64,${base64Image}`,
              detail: "high",
            },
          },
        ],
      },
    ],
    max_tokens: 500,
  });

  return response.choices[0].message.content || "";
};

// Main conversation processing function
const processConversation = async (ctx: Context) => {
  console.log("processConversation");
  if (!ctx.message || !("photo" in ctx.message) || !ctx.from) {
    return;
  }

  const userId = ctx.from.id;
  const photo = ctx.message.photo[ctx.message.photo.length - 1];
  const file = await ctx.telegram.getFile(photo.file_id);

  if (!file.file_path) {
    return;
  }

  // Download the file as a Buffer
  const response = await fetch(
    (await ctx.telegram.getFileLink(photo.file_id)).toString()
  );
  const fileContent = await response.arrayBuffer();

  // Extract text from image
  const conversationText = await extractTextFromImage(Buffer.from(fileContent));

  console.log("conversationText", conversationText);

  // Split text into chunks
  const textSplitter = new CharacterTextSplitter({
    separator: "\n",
    chunkSize: 1000,
    chunkOverlap: 200,
  });
  const texts = textSplitter.splitText(conversationText);

  // Create or update user's vector store
  // if (!conversationStores[userId]) {
  //   console.log("Creating vector store");
  //   conversationStores[userId] = await FaissStore.fromTexts(
  //     await texts,
  //     {},
  //     embeddings
  //   );
  // } else {
  //   await conversationStores[userId].addTexts(texts);
  // }
  console.log("texts", await texts);

  await ctx.reply(await getMessage(userId, "processedConversation"));
};

async function processPhoto(ctx: Context): Promise<void> {
  console.log("Processing photo...");
  const userId = ctx.from?.id;
  if (!userId || !ctx.message || !("photo" in ctx.message)) return;

  const userLanguage = await getUserLanguage(userId);

  const photo = ctx.message.photo[ctx.message.photo.length - 1];
  const file = await ctx.telegram.getFile(photo.file_id);
  if (!file.file_path) {
    return;
  }

  // Download the file as a Buffer
  const fileResponse = await fetch(
    (await ctx.telegram.getFileLink(photo.file_id)).toString()
  );
  const fileContent = await fileResponse.arrayBuffer();

  // Process the image using describeImage instead of extractTextFromImage
  const description = await describeImage(Buffer.from(fileContent));

  // Generate a response message
  const userMessage =
    `The user sent a picture. Here's what I see: ${description}\n\n` +
    `You are The Rizzard, a casual and confident dating coach. Remember to:\n` +
    `- Write exactly like a human friend texting advice\n` +
    `- Skip any explanations or meta-commentary\n` +
    `- Keep responses short and actionable (1-2 sentences max)\n` +
    `- Use casual language and natural texting style\n` +
    `- Be playful and confident in your suggestions\n` +
    `- If you see a dating profile, analyze their vibe and suggest a unique opener\n` +
    `- If you see a conversation, give specific advice on what to say next\n` +
    `- If you see profile or profile picture that might match the user, and the user asked about his profile review, give an advice about it\n` +
    `- Match their energy but maintain your mentor status\n\n` +
    `For the first message, format your response as either:\n` +
    `'{Quick profile analysis} + {Suggested opener}'\n` +
    `or\n` +
    `'{Quick conversation analysis} + {What to say next}'\n` +
    `or\n` +
    `'{Quick profile review} + {Advice about the profile}'` +
    `For the next messages, you should answer like a human friend would, with short, casual sentences.` +
    `Don't write template titles, just answer with the content.`;

  const response = await chainWithHistory.invoke(
    {
      question: userMessage,
      language: userLanguage,
    },
    {
      configurable: {
        sessionId: userId.toString(),
        language: userLanguage,
      },
    }
  );

  const enhancedResponse = await enhanceResponseStyle(
    userId,
    response.content.toString()
  );
  await ctx.reply(enhancedResponse);
}

// Add the handler
bot.on("photo", async (ctx, next) => {
  // if (ctx.message?.caption === "learn") {
  //   await processConversation(ctx);
  // } else {
  await processPhoto(ctx);
  // }
});

async function handleMessage(ctx: Context): Promise<void> {
  console.log("Handling message...");
  const userId = ctx.from?.id;
  if (!userId) return;

  const messageText =
    ctx.message && "text" in ctx.message ? ctx.message.text : undefined;
  if (!messageText) return;

  console.log("Text received from user:", userId, "message:", messageText);

  // Check configuration flow first
  const configStep = await getConfigurationStep(userId);
  if (configStep === "name") {
    console.log("Processing name input for user:", userId);
    await configureUser(userId, { name: messageText });
    await setConfigurationStep(userId, "gender");

    const genderKeyboard: InlineKeyboardMarkup = {
      inline_keyboard: [
        [
          {
            text: await getMessage(userId, "male"),
            callback_data: "set_gender_male",
          },
          {
            text: await getMessage(userId, "female"),
            callback_data: "set_gender_female",
          },
        ],
      ],
    };

    await ctx.reply(await getMessage(userId, "askGender"), {
      reply_markup: genderKeyboard,
    });
    return;
  }

  // Check awaiting input
  const awaitingInput = await getUserAwaitingInput(userId);
  if (awaitingInput === "name") {
    await configureUser(userId, { name: messageText });
    await ctx.reply(
      await getMessage(userId, "configType", {
        config_type: await getMessage(userId, "name"),
        value: messageText,
      })
    );
    await clearUserAwaitingInput(userId);
    return;
  }

  // Handle regular messages with debounce
  const existingTask = typingTasks[userId];
  if (existingTask) {
    clearTimeout(existingTask);
  }

  typingTasks[userId] = setTimeout(
    () => processMessageWithDelay(ctx, messageText),
    DEBOUNCE_DELAY
  );
}

// Use single handler
bot.on("text", handleMessage);

async function processMessageWithDelay(
  ctx: Context,
  messageText: string
): Promise<void> {
  const userId = ctx.from?.id;
  if (!userId) return;

  try {
    const userLanguage = await getUserLanguage(userId); // Still needed for configurable

    const response = await chainWithHistory.invoke(
      {
        question: new HumanMessage(messageText),
        language: userLanguage,
      },
      {
        configurable: {
          sessionId: userId.toString(),
          language: userLanguage,
        },
      }
    );

    const enhancedResponse = await enhanceResponseStyle(
      userId,
      response.content.toString()
    );
    await ctx.reply(enhancedResponse);
  } catch (error) {
    console.error("Error processing message:", error);
    await ctx.reply(await getMessage(userId, "errorProcessing"));
  }
}

async function enhanceResponseStyle(
  userId: number,
  responseText: string
): Promise<string> {
  const parts = responseText.split(/you should say/i);
  if (parts.length !== 2) return responseText;

  const [context, suggestion] = parts;
  const docs = await conversationStores[userId].similaritySearch(suggestion, 2);
  const styleExamples = docs.map((doc: any) => doc.pageContent).join("\n");

  const stylePrompt = `Based on these example messages that show the user's writing style:
    ${styleExamples}
    
    Rewrite this message to match their style: ${suggestion}
    
    Keep the same meaning but adapt the tone, vocabulary, and punctuation to match how they typically write. Make it slightly more casual and less formal.`;

  const styleResponse = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: stylePrompt }],
    temperature: 0.7,
  });

  const styledSuggestion =
    styleResponse.choices[0].message.content || suggestion;
  return `${context}you should say${styledSuggestion}`;
}

async function describeImage(image: Buffer): Promise<string> {
  console.log("Describing image...");
  const base64Image = image.toString("base64");

  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text:
              "What does this image represent in the context of a dating profile or conversation? Analyze the text, images, or any visible details to identify:\n" +
              "- Key personality traits, interests, or preferences expressed.\n" +
              "- The tone or mood conveyed by the profile or conversation.\n" +
              "- Any specific details that could guide the user in crafting a thoughtful response or message.",
          },
          {
            type: "image_url",
            image_url: {
              url: `data:image/jpeg;base64,${base64Image}`,
              detail: "low",
            },
          },
        ],
      },
    ],
    max_tokens: 300,
  });

  return response.choices[0].message.content || "";
}

// Update the error handler interface
interface BotError extends Error {
  response?: {
    error_code?: number;
    description?: string;
  };
  description?: string;
  code?: string;
}

// Update the error handler
const errorHandler = async (error: BotError, ctx: Context) => {
  console.error("Error details:", {
    message: error.message,
    code: error.code,
    response: error.response,
    stack: error.stack,
  });

  const userId = ctx.from?.id;
  if (!userId) {
    console.error("No user ID available in error context");
    return;
  }

  try {
    // Send a user-friendly error message
    const errorMessage = await getMessage(userId, "errorGeneric");
    await ctx.reply(errorMessage);
  } catch (e) {
    console.error("Error while sending error message:", e);
    // Attempt to send a basic error message as fallback
    try {
      await ctx.reply("An error occurred. Please try again later.");
    } catch (finalError) {
      console.error("Failed to send fallback error message:", finalError);
    }
  }
};

// Update how we attach the error handler
bot.catch(async (err: unknown, ctx: Context) => {
  await errorHandler(err as BotError, ctx);
});

// Add new Redis helper functions
async function getConfigurationStep(userId: number): Promise<string | null> {
  return redis.get(`user:${userId}:config_step`) as Promise<string | null>;
}

async function setConfigurationStep(
  userId: number,
  step: string | null
): Promise<void> {
  if (step === null) {
    await redis.del(`user:${userId}:config_step`);
  } else {
    await redis.set(`user:${userId}:config_step`, step);
  }
}

const port = process.env.PORT || 3000;
const telegramPort = process.env.TELEGRAM_PORT || 3001;
const app = express();

// Setup Express middleware
app.use(express.json());

// Health check endpoint
app.get("/health", (req, res) => {
  res.status(200).json({ status: "ok" });
});

// Webhook endpoint
app.post("/webhook", (req, res) => {
  bot.handleUpdate(req.body, res);
});

app.get("/test", (req, res) => {
  res.send(`Hello ${req.query.name}`);
});

// Validate environment variables
if (!openaiApiKey || !telegramApiKey || !stripePublicKey || !stripeSecretKey) {
  throw new Error("Missing required environment variables");
}

// Setup webhook URL
const webhookUrl = process.env.WEBHOOK_URL;
if (!webhookUrl) {
  throw new Error("Missing WEBHOOK_URL environment variable");
}

// Configure webhook
bot.telegram.setWebhook(`${webhookUrl}/webhook`);
// bot.launch({
//   webhook: {
//     // Public domain for webhook; e.g.: example.com
//     domain: webhookUrl,

//     // Port to listen on; e.g.: 8080
//     port: Number(telegramPort),
//   },
// });
console.log("Webhook set successfully");

// Start Express server
app.listen(port, () => {
  console.log(`Server is running on port ${port}`);
});

// Add unhandled rejection handler
process.on("unhandledRejection", (reason, promise) => {
  console.error("Unhandled Rejection at:", promise, "reason:", reason);
});

// Add uncaught exception handler
process.on("uncaughtException", (error) => {
  console.error("Uncaught Exception:", error);
});
