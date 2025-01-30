import { CharacterTextSplitter } from "@langchain/textsplitters";
import { Context } from "telegraf";
import {
  chainWithHistory,
  client,
  DEBOUNCE_DELAY,
  isDev,
  redis,
  supabase,
  typingTasks,
} from "./config";
import { DEFAULT_CONFIG, MESSAGES } from "./constants";
import { UserConfig } from "./types";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";
import { InlineKeyboardMarkup } from "telegraf/typings/core/types/typegram";

// Add Redis helper functions
export async function getUserConfig(
  userId: number | string
): Promise<UserConfig | null> {
  const config = await redis.get(`user:${userId}:config`);
  return config
    ? typeof config === "string"
      ? JSON.parse(config)
      : config
    : null;
}

export function calculateAge(date: string): number {
  const today = new Date();
  const birthdate = new Date(date);
  let age = today.getFullYear() - birthdate.getFullYear();
  const monthDiff = today.getMonth() - birthdate.getMonth();
  if (
    monthDiff < 0 ||
    (monthDiff === 0 && today.getDate() < birthdate.getDate())
  ) {
    age--;
  }
  return age;
}

// Add new Redis helper functions
export async function getConfigurationStep(
  userId: number | string
): Promise<string | null> {
  return redis.get(`user:${userId}:config_step`) as Promise<string | null>;
}

export async function setConfigurationStep(
  userId: number | string,
  step: string | null
): Promise<void> {
  if (step === null) {
    await redis.del(`user:${userId}:config_step`);
  } else {
    await redis.set(`user:${userId}:config_step`, step);
  }
}

export async function setUserConfig(
  userId: number | string,
  config: Partial<UserConfig>
): Promise<void> {
  const currentConfig = (await getUserConfig(userId)) || { ...DEFAULT_CONFIG };
  const newConfig = {
    ...currentConfig,
    ...(config.birthdate
      ? { birthdate: new Date(config.birthdate.split("/").reverse().join("-")) }
      : config),
  };
  await redis.set(`user:${userId}:config`, JSON.stringify(newConfig));
  await supabase.from("users").update(newConfig).eq("app_id", userId);
}

export const parseResponse = async (response: string, ctx: Context) => {
  console.log("parseResponse", response);
  if (response.startsWith("{")) {
    const parsed = JSON.parse(response);
    const isPhoto = ctx.message && "photo" in ctx?.message;

    if (isPhoto) await ctx.reply(parsed.comment);
    else await ctx.editMessageText(parsed.comment);
    // wait 0.5 seconds
    await new Promise((resolve) => setTimeout(resolve, 500));

    for (const opener of parsed.openers) {
      await ctx.reply(opener);
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  } else {
    await ctx.reply(response);
  }
};

export async function getUserLanguage(
  userId: number | string
): Promise<string> {
  try {
    const config = await getUserConfig(userId);
    return (config?.language as string) || "en";
  } catch (error) {
    console.error("Redis error getting language:", error);
    return "en"; // Fallback to English
  }
}

// Update the configureUser function to be async
export const configureUser = async (
  userId: number | string,
  config: Partial<UserConfig>
): Promise<void> => {
  await setUserConfig(userId, config);
};

// Update getMessage function to be async
export async function getMessage(
  userId: number | string,
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

// Add Redis helper functions for temporary states
export async function setUserAwaitingInput(
  userId: number | string,
  inputType: string
): Promise<void> {
  await redis.set(`user:${userId}:awaiting_input`, inputType);
}

export async function getUserAwaitingInput(
  userId: number | string
): Promise<string | null> {
  return redis.get(`user:${userId}:awaiting_input`) as Promise<string | null>;
}

export async function clearUserAwaitingInput(
  userId: number | string
): Promise<void> {
  await redis.del(`user:${userId}:awaiting_input`);
}

// Add helper function for image processing
export const extractTextFromImage = async (image: Buffer): Promise<string> => {
  console.log("extractTextFromImage");
  const base64Image = image.toString("base64");

  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    temperature: 0.8,
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
export const processConversation = async (ctx: Context) => {
  console.log("processConversation");
  if (!ctx.message || !("photo" in ctx.message) || !ctx.from) {
    return;
  }

  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
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

export async function processPhoto(
  ctx: Context,
  caption?: string
): Promise<void> {
  console.log("Processing photo...");
  await ctx.sendChatAction("upload_photo");
  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
  if (!userId || !ctx.message || !("photo" in ctx.message)) return;

  await ctx.reply(await getMessage(userId, "processingPhoto"));
  const userLanguage = await getUserLanguage(userId);

  const photo = ctx.message.photo[ctx.message.photo.length - 1];
  const file = await ctx.telegram.getFile(photo.file_id);
  if (!file.file_path) return;

  // Download the file as a Buffer
  const fileResponse = await fetch(
    (await ctx.telegram.getFileLink(photo.file_id)).toString()
  );
  const fileContent = await fileResponse.arrayBuffer();

  // Process the image using describeImage instead of extractTextFromImage
  const description = await describeImage(Buffer.from(fileContent));
  console.log("Image description:", description);

  await ctx.sendChatAction("typing");
  // Use a simple message that includes the image description
  const response = await chainWithHistory.invoke(
    {
      question: `[IMAGE ANALYSIS] ${description}
        ${caption ? `[USER MESSAGE] ${caption}` : ""}`,
      language: userLanguage,
    },
    {
      configurable: {
        sessionId: userId.toString(),
        language: userLanguage,
      },
    }
  );

  // const enhancedResponse = await enhanceResponseStyle(
  //   userId,
  //   response.content.toString()
  // );
  const parsedResponse = response.content.toString();
  await parseResponse(parsedResponse, ctx);
}

export async function handleMessage(ctx: Context): Promise<void> {
  console.log("Handling message...");
  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
  if (!userId) return;

  await ctx.sendChatAction("typing");

  const messageText =
    ctx.message && "text" in ctx.message ? ctx.message.text : undefined;
  if (!messageText) return;

  console.log("Text received from user:", userId, "message:", messageText);

  // Check configuration flow first
  const configStep = await getConfigurationStep(userId);
  if (configStep === "name") {
    console.log("Processing name input for user:", userId);
    await configureUser(userId, { name: messageText });
    await setConfigurationStep(userId, "birthdate");

    await chainWithHistory.invoke(
      {
        question: new SystemMessage(
          `[CONFIG UPDATE] User has set their name to ${messageText}. Please consider this in future interactions and suggestions.`
        ),
      },
      {
        configurable: {
          sessionId: userId.toString(),
        },
      }
    );

    await ctx.reply(
      await getMessage(userId, "askBirthdate", {
        format: "DD/MM/YYYY",
      })
    );
    return;
  }

  if (configStep === "birthdate") {
    // Validate birthdate format (DD/MM/YYYY)
    const birthdateRegex = /^(0[1-9]|[12][0-9]|3[01])\/(0[1-9]|1[0-2])\/\d{4}$/;

    if (!birthdateRegex.test(messageText)) {
      await ctx.reply(
        await getMessage(userId, "invalidBirthdate", {
          format: "DD/MM/YYYY",
        })
      );
      return;
    }

    // Store birthdate
    await configureUser(userId, { birthdate: messageText });
    await setConfigurationStep(userId, "gender");

    await chainWithHistory.invoke(
      {
        question: new SystemMessage(
          `[CONFIG UPDATE] User has set their birthdate to ${messageText} with format DD/MM/YYYY. Please consider this in future interactions and suggestions.`
        ),
        language: await getUserLanguage(userId),
      },
      {
        configurable: {
          sessionId: userId.toString(),
        },
      }
    );

    // Show gender selection keyboard
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

export async function processMessageWithDelay(
  ctx: Context,
  messageText: string
): Promise<void> {
  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
  if (!userId) return;
  await ctx.sendChatAction("typing");

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

    // const enhancedResponse = await enhanceResponseStyle(
    //   userId,
    //   response.content.toString()
    // );
    await parseResponse(response.content.toString(), ctx);
  } catch (error) {
    console.error("Error processing message:", error);
    await ctx.reply(await getMessage(userId, "errorProcessing"));
  }
}

export async function enhanceResponseStyle(
  userId: number | string,
  responseText: string
): Promise<string> {
  console.log("enhanceResponseStyle");
  const parts = responseText.split(/you should say/i);
  console.log("parts", parts.length);
  return responseText;

  // const [context, suggestion] = parts;
  // const docs = await conversationStores[userId].similaritySearch(suggestion, 2);
  // const styleExamples = docs.map((doc: any) => doc.pageContent).join("\n");

  // const stylePrompt = `Based on these example messages that show the user's writing style:
  //   ${styleExamples}

  //   Rewrite this message to match their style: ${suggestion}

  //   Keep the same meaning but adapt the tone, vocabulary, and punctuation to match how they typically write. Make it slightly more casual and less formal.`;

  // const styleResponse = await client.chat.completions.create({
  //   model: "gpt-4o-mini",
  //   messages: [{ role: "user", content: stylePrompt }],
  //   temperature: 0.7,
  // });

  // const styledSuggestion =
  //   styleResponse.choices[0].message.content || suggestion;
  // return `${context}you should say${styledSuggestion}`;
}

export async function describeImage(image: Buffer): Promise<string> {
  console.log("Describing image...");
  const base64Image = image.toString("base64");

  const response = await client.chat.completions.create({
    model: "gpt-4o-mini",
    temperature: 0.8,
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text:
              "What does this image represent in the context of a dating profile or conversation? Analyze the text, images, or any visible details.\n" +
              "If it's a conversation, extract the conversation text from the image.\n" +
              "Don't answer in markdown format, just plain text.",
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
