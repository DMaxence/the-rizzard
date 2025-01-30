import { SystemMessage } from "@langchain/core/messages";
import { Context, Telegraf } from "telegraf";
import { InlineKeyboardMarkup } from "telegraf/types";
// import { FaissStore } from "@langchain/community/vectorstores/faiss";

import express from "express";
import {
  chainWithHistory,
  DEBOUNCE_DELAY,
  isDev,
  logsnag,
  port,
  redis,
  supabase,
  telegramApiKey,
  typingTasks,
  webhookUrl,
} from "./config";
import {
  calculateAge,
  clearUserAwaitingInput,
  configureUser,
  getConfigurationStep,
  getMessage,
  getUserAwaitingInput,
  getUserConfig,
  getUserLanguage,
  handleMessage,
  processMessageWithDelay,
  processPhoto,
  setConfigurationStep,
  setUserAwaitingInput,
  setUserConfig,
} from "./utils";

const bot = new Telegraf(telegramApiKey);

// Add start command handler
bot.command("start", async (ctx) => {
  const userId = isDev ? `${ctx.from.id}-dev` : ctx.from.id;
  console.log("Start command received for user:", userId);

  // Check if user already exists
  const existingConfig = await getUserConfig(userId);
  if (existingConfig) {
    await ctx.reply(
      await getMessage(userId, "welcomeBack", {
        name: ctx.from.first_name,
      })
    );
    if (!isDev) {
      await logsnag.identify({
        user_id: userId.toString(),
        properties: {
          username: ctx.from.username || "someone",
          platform: "telegram",
        },
      });
    }
    return;
  }

  // Track new user with LogSnag
  if (!isDev) {
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
      notify: true,
    });
  }

  // Add user to Supabase
  const { error } = await supabase.from("users").insert([
    {
      app_id: ctx.from.id,
      username: ctx.from.username || null,
      name: ctx.from.first_name,
      language: ctx.from.language_code || "en",
      gender: null,
      birthdate: null,
      sexual_preference: null,
      platform: isDev ? "telegram-dev" : "telegram",
    },
  ]);

  if (error) {
    console.error("Error adding user to Supabase:", error);
  }

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

bot.command(["settings", "setting"], async (ctx) => {
  const userId = isDev ? `${ctx.from.id}-dev` : ctx.from.id;
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
          text: await getMessage(userId, "birthdate"),
          callback_data: "config_birthdate",
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
  await ctx.sendChatAction("typing");

  const userId = isDev ? `${ctx.from.id}-dev` : ctx.from.id;
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

    case "birthdate":
      await ctx.editMessageText(await getMessage(userId, "askBirthdate"));
      await setUserAwaitingInput(userId, "birthdate");
      break;

    case "style":
      await ctx.editMessageText(await getMessage(userId, "styleInstructions"));
      break;
  }
});

// Modify the language callback handler to handle both initial setup and settings changes
bot.action(/^set_language_(.+)$/, async (ctx) => {
  if (!ctx.callbackQuery || !("data" in ctx.callbackQuery) || !ctx.from) return;

  await ctx.sendChatAction("typing");

  const userId = isDev ? `${ctx.from.id}-dev` : ctx.from.id;
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

  await ctx.sendChatAction("typing");

  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
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

  await ctx.sendChatAction("typing");

  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
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
        age: config?.birthdate
          ? calculateAge(config.birthdate).toString()
          : "??",
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

// Add the handler
bot.on("photo", async (ctx, next) => {
  // if (ctx.message?.caption === "learn") {
  //   await processConversation(ctx);
  // } else {
  await processPhoto(ctx, ctx.message?.caption);
  // }
});



// Use single handler
bot.on("text", handleMessage);

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

  const userId = isDev ? `${ctx.from?.id}-dev` : ctx.from?.id;
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

console.log("NODE_ENV", process.env.NODE_ENV);
if (process.env.NODE_ENV !== "development") {
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

  // Configure webhook
  bot.telegram.setWebhook(`${webhookUrl}/webhook`);
  console.log("Webhook set successfully");

  // Start Express server
  app.listen(port, () => {
    console.log(`Server is running on port ${port}`);
  });
} else {
  bot.launch();
}

// Add unhandled rejection handler
process.on("unhandledRejection", (reason, promise) => {
  console.error("Unhandled Rejection at:", promise, "reason:", reason);
});

// Add uncaught exception handler
process.on("uncaughtException", (error) => {
  console.error("Uncaught Exception:", error);
});
