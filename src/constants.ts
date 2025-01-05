import { Messages } from "./types";
// Message translations
export const MESSAGES: Messages = {
  en: {
    askName: "Great! Now, what's your name?",
    askGender: "Thanks! Now, what's your gender?",
    askPreference: "What's your sexual preference?",
    settingsPrompt: "What would you like to change?",
    askNameSettings: "Please enter your name:",
    male: "Male",
    female: "Female",
    heterosexual: "Heterosexual",
    homosexual: "Homosexual",
    bisexual: "Bisexual",
    name: "Name",
    gender: "Gender",
    sexualPreference: "Sexual Preference",
    language: "Language",
    uploadStyle: "Upload Conversation Style",
    settingsSaved:
      "Your settings have been saved. You can edit them anytime by typing /settings",
    configType: "Your {config_type} has been updated to: {value}",
    styleInstructions:
      "To help me understand your conversation style, send me screenshots of your past conversations with the caption 'learn'.",
    settingsSummary:
      "Perfect! Here are your settings:\n\n" +
      "Name: {name}\n" +
      "Gender: {gender}\n" +
      "Sexual Preference: {preference}\n" +
      "Language: {language}\n\n" +
      "Your settings have been saved. You can edit them anytime by typing /settings\n\n" +
      "How can I help you?",

    // Would you like to help me understand your conversation style?
    // To help me understand your conversation style, send me screenshots of your past conversations with the caption 'learn'.`,
    processedConversation:
      "Thanks! I've learned from your conversation style. I'll use this to provide more personalized suggestions.",
    genderUpdated: "Your gender has been set to: {gender}",
    preferenceUpdated: "Your sexual preference has been set to: {preference}",
    errorProcessing:
      "Sorry, I couldn't process your message. Please try again.",
    errorProcessingMedia:
      "Sorry, I couldn't process your media. Please try again.",
    errorPayment:
      "Sorry, there was an error processing your payment. Please try again.",
    errorGeneric: "An error occurred. Please try again.",
    premiumPaymentLink: "Click here to unlock premium features: {paymentUrl}",
    welcomeBack:
      "Hi {name} ! You already configured your bot, to change your settings, type /settings instead",
  },
  fr: {
    askName: "Super ! Comment tu t'appelles ?",
    askGender: "Merci ! Maintenant, quel est ton genre ?",
    askPreference: "Quelle est ta préférence sexuelle ?",
    settingsPrompt: "Que souhaites-tu modifier ?",
    askNameSettings: "Entre ton nom :",
    male: "Homme",
    female: "Femme",
    heterosexual: "Hétérosexuel",
    homosexual: "Homosexuel",
    bisexual: "Bisexuel",
    name: "Nom",
    gender: "Genre",
    sexualPreference: "Préférence sexuelle",
    language: "Langue",
    uploadStyle: "Télécharger style de conversation",
    settingsSaved:
      "Tes paramètres ont été enregistrés. Tu peux les modifier à tout moment en tapant /settings",
    configType: "Ton {config_type} a été mis à jour à : {value}",
    styleInstructions:
      "Pour m'aider à comprendre ton style de conversation, envoie-moi des captures d'écran de tes conversations passées avec la légende 'learn'.",
    settingsSummary:
      "Parfait ! Voici tes paramètres :\n\n" +
      "Nom : {name}\n" +
      "Genre : {gender}\n" +
      "Préférence sexuelle : {preference}\n" +
      "Langue : {language}\n\n" +
      "Tes paramètres ont été enregistrés. Tu peux les modifier à tout moment en tapant /settings\n\n" +
      "Comment je peux t'aider ?",

    // Tu veux m'aider à comprendre ton style de conversation ?
    // Pour m'aider à comprendre ton style de conversation, envoie-moi des captures d'écran de tes conversations passées avec la légende 'learn'.`,
    processedConversation:
      "Merci ! J'ai appris de ton style de conversation. Je vais l'utiliser pour fournir des suggestions plus personnalisées.",
    genderUpdated: "Ton genre a été défini sur : {gender}",
    preferenceUpdated:
      "Ta préférence sexuelle a été définie sur : {preference}",
    errorProcessing:
      "Désolé, je n'ai pas pu traiter ton message. Essaie à nouveau.",
    errorProcessingMedia:
      "Désolé, je n'ai pas pu traiter ton média. Essaie à nouveau.",
    errorPayment:
      "Désolé, il y a eu une erreur lors du traitement de ton paiement. Essaie à nouveau.",
    errorGeneric: "Une erreur s'est produite. Essaie à nouveau.",
    premiumPaymentLink:
      "Clique ici pour débloquer les fonctionnalités premium : {paymentUrl}",
    welcomeBack:
      "Salut {name} ! Tu as déjà configuré ton bot, pour modifier tes paramètres, tape /settings à la place",
  },
};
