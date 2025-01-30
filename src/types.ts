// Types
export interface UserConfig {
  name: string | null;
  gender: string | null;
  sexual_preference: string | null;
  language: string;
  birthdate?: string;
}

export interface Messages {
  [key: string]: {
    [key: string]: string;
  };
}

export interface ChatHistory {
  messages: Array<{
    role: "user" | "assistant";
    content: string;
  }>;
}
