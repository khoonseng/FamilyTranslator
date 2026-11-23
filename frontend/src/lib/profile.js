// Language profiles (owner decision 2026-11-23): one bundle, one profile per Cloud Run service.
// The server names the profile in index.html (<meta name="profile">); the Chongqing service
// serves the built page untouched, so it always reads "chongqing".
//
// Only the words that change with the language pair live here; English-only text stays in the
// components. The Chongqing table is the app's wording as it was before profiles, verbatim:
// the guide reads Mandarin on the hub, the family reads Cantonese.

const chongqing = {
  appName: "重慶翻譯",

  // The hub, read by the guide.
  hubGuide: "导游 Guide",
  hubStop: "停止 Stop",
  hubRepliesWaiting: (n) => `${n} 个回覆等导游停一停 · ${n} waiting for the guide to pause`,
  hubTypePlaceholder: "输入普通话 Type Mandarin",
  hubEmpty: "Tap Guide and speak Mandarin, or type it above.",
  hubFamilyAsks: "家人问 · Family asks",
  hubReplyNotTranslated: "未能翻译 · Not translated: please interpret",

  // Host phones: the text that goes with the family's join link.
  shareText: "撳呢條連結，聽導遊講嘅廣東話：",

  // Family phones.
  mediaArtist: "廣東話 Cantonese",
  linkRevoked: "呢條連結已經唔用得。請喺家庭 WhatsApp 群組撳新連結。",
  openLink: "請喺家庭 WhatsApp 群組撳連結加入。",
  earphones: "請戴上耳筒，然後撳「開始」。",
  start: "開始 Start",
  soundOffTextOnly: "靜音：只顯示文字 · Sound off: text only",
  reconnecting: "重新連線中… · Reconnecting…",
  hubOffline: "導遊手機離線 · Hub offline",
  guidePaused: "暫停收聽 · Guide listening paused",
  autoPlay: "自動播放 Auto-play",
  english: "英文 English",
  soundOff: "靜音 Sound off",
  waitingForGuide: "等緊導遊講嘢… · Waiting for the guide…",
  you: "你 · You",
  family: "家人 · Family",
  notTranslated: "未能翻譯 · Not translated",
  play: "播放 Play",
  jumpToLatest: "跳到最新 · Jump to latest",
  playNew: (n) => `播放 ${n} 句新嘅 · Play ${n} new`,
  tapToResume: "撳呢度繼續播放 · Tap to resume audio",

  // Talk (phase 2), on family phones.
  talkGuideSpeaking: "導遊講緊嘢… · Guide is speaking…",
  talkSomeoneAsking: "有人問緊… · Someone is asking…",
  talkOpeningMic: "開緊咪… · Opening mic…",
  talkRelease: (s) => `講完放手 · Release to send · ${s}s`,
  talkHold: "🎤 撳住講 · Hold to talk",
  talkGuideStarted: "導遊啱啱開口，等佢講完先 · The guide started talking: wait for a pause.",
  talkSomeoneElse: "有人問緊，等一陣 · Someone else is asking: wait a moment.",
  talkTypePlaceholder: "打字問導遊 · Type to the guide",
  talkSend: "發送 Send",
  talkPinWrong: "PIN 唔啱 · That PIN wasn't accepted.",
  talkAsk: "🙋 問導遊 · Ask the guide",
};

export const PROFILES = { chongqing };

export const DEFAULT_PROFILE = "chongqing";

/** The profile the server named in the page, or Chongqing (tests, an unknown name). */
export function profileName(doc = globalThis.document) {
  const name = doc?.querySelector?.('meta[name="profile"]')?.content;
  return name && Object.hasOwn(PROFILES, name) ? name : DEFAULT_PROFILE;
}

export const text = PROFILES[profileName()];
