import { UpstashRedisChatMessageHistory } from "@langchain/community/stores/message/upstash_redis";
import {
  ChatPromptTemplate,
  MessagesPlaceholder,
} from "@langchain/core/prompts";
import { RunnableWithMessageHistory } from "@langchain/core/runnables";
import { ChatOpenAI } from "@langchain/openai";
import { Redis } from "@upstash/redis";
import { OpenAIEmbeddings } from "langchain/embeddings/openai";
import { OpenAI } from "openai";
import Stripe from "stripe";
// import { FaissStore } from "@langchain/community/vectorstores/faiss";

import { LogSnag } from "@logsnag/node";
import { createClient } from "@supabase/supabase-js";
import { PROMPT } from "./constants";

// Load environment variables
const openaiApiKey = process.env.OPENAI_API_KEY || "";
const telegramApiKey = process.env.TELEGRAM_BOT_TOKEN || "";
const stripePublicKey = process.env.STRIPE_PUBLIC_KEY || "";
const stripeSecretKey = process.env.STRIPE_SECRET_KEY || "";
const logsnagToken = process.env.LOGSNAG_TOKEN || "";
const supabaseKey = process.env.SUPABASE_ANON_KEY || "";
const supabaseUrl = process.env.SUPABASE_URL || "";
const webhookUrl = process.env.WEBHOOK_URL || "";
const port = process.env.PORT || 3000;
const isDev = process.env.NODE_ENV === "development";

// Setup webhook URL

if (
  !openaiApiKey ||
  !telegramApiKey ||
  !stripePublicKey ||
  !stripeSecretKey ||
  !logsnagToken ||
  !supabaseKey ||
  !supabaseUrl ||
  (!webhookUrl && !isDev)
) {
  throw new Error("Missing required environment variables");
}

// Initialize Stripe
const stripe = new Stripe(stripeSecretKey, { apiVersion: "2022-11-15" });

// Initialize OpenAI
const model = new ChatOpenAI({ model: "gpt-4o-mini", temperature: 0.7 });
const client = new OpenAI({ apiKey: openaiApiKey });

// Initialize Redis client (after other initializations)
const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL!,
  token: process.env.UPSTASH_REDIS_REST_TOKEN!,
});

// Initialize LogSnag
const logsnag = new LogSnag({
  token: logsnagToken,
  project: "the-rizzard",
});

// Initialize Supabase client
const supabase = createClient(supabaseUrl, supabaseKey);

// Initialize vector store for conversation history
const embeddings = new OpenAIEmbeddings();
const conversationStores: Record<number | string, any> = {};

// Store typing tasks per user
const typingTasks: Record<number | string, NodeJS.Timeout> = {};
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

export {
  chainWithHistory,
  client,
  DEBOUNCE_DELAY,
  isDev,
  logsnag,
  port,
  redis,
  supabase,
  telegramApiKey,
  typingTasks,
  webhookUrl,
};
