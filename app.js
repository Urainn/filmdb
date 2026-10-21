const FILMDB_BASE = (() => {
  try {
    const host = String(location.hostname || "").toLowerCase();
    // 與後端同站時走同源，避免跨域／設備登入同步被擋
    if (
      host.includes("onrender.com") ||
      host === "localhost" ||
      host === "127.0.0.1"
    ) {
      return location.origin;
    }
  } catch (_) {}
  return "https://filmdb-68z4.onrender.com";
})();

/*
  這裡會自動嘗試多個常見資料路徑。
  如果你們之後知道正式 API，例如 /api/movies，只要把它放在第一個即可。
*/
const API_CANDIDATES = [
  // 依照 Network 看到的結果，你的實際資料頁是 /db，所以優先讀這個
  `${FILMDB_BASE}/db`,

  // 下面是備用 API 路徑，如果之後後端有開 JSON API 也會自動嘗試
  `${FILMDB_BASE}/api/movies`,
  `${FILMDB_BASE}/api/films`,
  `${FILMDB_BASE}/api/movie`,
  `${FILMDB_BASE}/api/data`,
  `${FILMDB_BASE}/api/export`,
  `${FILMDB_BASE}/movies`,
  `${FILMDB_BASE}/films`,
  `${FILMDB_BASE}/data.json`,
  `${FILMDB_BASE}/movies.json`,
  `${FILMDB_BASE}/film-db.json`,
  `${FILMDB_BASE}/`
];

const AUTH_USERS_KEY = "moodluma-users";
const CURRENT_USER_KEY = "moodluma-current-user";
const AUTH_TOKEN_KEY = "moodluma-auth-token";
const HISTORY_PREFIX = "moodluma-history";
const FAVORITE_PREFIX = "moodluma-favorites";
const GUEST_ID = "guest";
const ROOM_KEY = "moodluma-current-room";
const ROOM_PREFIX = "ROOM-";
const MY_MEMBER_NAME_KEY = "moodluma-my-member-name";
let roomPollTimer = null;

function backendRoomCode(code) {
  return String(code || "").trim().toUpperCase().replace(/^ROOM-/, "").replace(/\s+/g, "");
}

function formatRoomCodeDisplay(code) {
  const c = backendRoomCode(code);
  return c ? `${ROOM_PREFIX}${c}` : `${ROOM_PREFIX}----`;
}

async function apiRoomCreate(roomName = "Moodluma") {
  const res = await fetch(`${FILMDB_BASE}/api/room/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roomName }),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "建立房間失敗");
  return data.room;
}

async function apiRoomJoin(roomCode, userName) {
  const res = await fetch(`${FILMDB_BASE}/api/room/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roomCode: backendRoomCode(roomCode), userName }),
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "加入房間失敗");
  return data.room;
}

async function apiRoomGet(roomCode) {
  const code = backendRoomCode(roomCode);
  const res = await fetch(`${FILMDB_BASE}/api/room?code=${encodeURIComponent(code)}`);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "查詢房間失敗");
  return data.room;
}

function applyServerMembers(room) {
  const names = Array.isArray(room?.members) ? room.members : [];
  const byName = new Map(groupMembers.map(m => [m.name, m]));
  groupMembers = names.map((name, i) => {
    const ex = byName.get(name);
    if (ex) return ex;
    return {
      id: `member-${backendRoomCode(getCurrentRoomCode())}-${i}-${String(name).replace(/\s+/g, "_")}`,
      name,
      tags: {},
      role: `role-${Math.min(i + 1, 5)}`,
    };
  });
  if (!activeMemberId || !groupMembers.some(m => m.id === activeMemberId)) {
    activeMemberId = groupMembers[0]?.id || null;
  }
  saveGroupMembers();
  renderMembers();
  renderGroupTags();
  renderRoleOptions();
}

function stopRoomPoll() {
  if (roomPollTimer) {
    clearInterval(roomPollTimer);
    roomPollTimer = null;
  }
}

function startRoomPoll() {
  stopRoomPoll();
  roomPollTimer = setInterval(async () => {
    try {
      const room = await apiRoomGet(getCurrentRoomCode());
      applyServerMembers(room);
    } catch (_) { /* ignore transient errors */ }
  }, 3000);
}

async function refreshRoomFromServer() {
  const room = await apiRoomGet(getCurrentRoomCode());
  applyServerMembers(room);
  return room;
}

async function initRoomFromServer() {
  let code = backendRoomCode(localStorage.getItem(ROOM_KEY));
  if (!code) {
    const created = await apiRoomCreate("Moodluma");
    code = created.code;
    localStorage.setItem(ROOM_KEY, code);
  } else {
    try {
      await apiRoomGet(code);
    } catch (_) {
      const created = await apiRoomCreate("Moodluma");
      code = created.code;
      localStorage.setItem(ROOM_KEY, code);
    }
  }
  updateRoomUI();
  groupVotes = loadGroupVotes();
  try {
    await refreshRoomFromServer();
  } catch (_) {
    groupMembers = [];
    activeMemberId = null;
    saveGroupMembers();
    renderMembers();
  }
  startRoomPoll();
}

/*
  支援中英文欄位名稱。
  資料庫若有「主要場景、次要場景、類型關鍵字、情感／氛圍」，
  這裡會自動抓來統整成圓圈標籤。
*/
const FIELD_MAP = {
  title: ["title", "name", "movieName", "movie_title", "電影名稱", "片名", "名稱"],
  desc: ["description", "desc", "overview", "plot", "summary", "story", "簡介", "介紹", "劇情簡介", "內容簡介"],
  poster: [
    "poster", "posterUrl", "poster_url",
    "thumbnail", "thumbnailUrl", "thumbnail_url",
    "image", "imageUrl", "image_url",
    "cover", "coverUrl", "cover_url",
    "img", "src",
    "youtubeThumbnail", "youtube_thumbnail",
    "縮圖", "海報", "圖片", "圖片網址", "封面", "封面圖片"
  ],
  trailer: ["youtubeUrl", "youtube_url", "trailer", "trailerUrl", "trailer_url", "url", "YouTube URL", "YouTube 網址", "預告片"],
  youtubeId: ["youtubeId", "youtube_id", "videoId", "video_id", "ytId", "yt_id", "YouTube ID", "影片ID", "影片 ID"],
  mainScene: [
    "scenesMain", "sceneMain", "mainScenes", "mainScene", "primaryScene",
    "scenes_main", "scene_main", "main_scenes", "main_scene", "scenes",
    "主要場景", "主場景", "場景"
  ],
  subScene: [
    "scenesSub", "sceneSub", "subScenes", "subScene", "secondaryScene",
    "scenes_sub", "scene_sub", "sub_scenes", "sub_scene", "次要場景", "副場景"
  ],
  genre: [
    "genreKeywords", "genre_keywords", "genres", "genre", "categories", "category", "types", "type",
    "類型關鍵字", "類型", "電影類型", "分類"
  ],
  mood: [
    "moodKeywords", "mood_keywords", "moods", "mood", "emotion", "emotions", "atmosphere",
    "feel", "feeling", "vibe", "情感／氛圍", "情感/氛圍", "情感", "氛圍", "情緒"
  ],
  year: ["year", "releaseYear", "release_year", "年份", "上映年份"],
  duration: ["duration", "runtime", "length", "片長", "時長"],
  views: ["views", "viewCount", "view_count", "clicks", "clickCount", "瀏覽次數", "點擊次數", "觀看次數"],
  actors: ["actors", "actor", "cast", "casts","演員", "演員名單", "主演", "卡司"],
  keywords: ["keywords", "keyword", "tags", "tag", "關鍵字", "標籤", "電影關鍵字"],
};

const FALLBACK_MOVIES = [
  {
    id: "fallback-1",
    title: "Midnight Signal",
    desc: "一名工程系學生在深夜接收到來自禁區基地的神秘訊號，卻發現這段訊號會改變人的記憶。",
    poster: "assets/poster1.png",
    genre: ["科幻片", "懸疑"],
    mood: ["孤獨", "深夜感", "壓迫感"],
    mainScene: ["禁區", "雨夜"],
    subScene: ["山區", "實驗基地"],
    year: "2026",
    duration: "1 小時 58 分",
    trailer: ""
  },
  {
    id: "fallback-2",
    title: "Blue Harbor",
    desc: "失去方向的女孩回到海港小鎮，重新面對家庭、傷口與未完成的告別。",
    poster: "assets/poster2.png",
    genre: ["劇情片"],
    mood: ["療癒", "安靜", "海風感"],
    mainScene: ["海邊", "小鎮"],
    subScene: ["燈塔", "港口"],
    year: "2025",
    duration: "2 小時 04 分",
    trailer: ""
  },
  {
    id: "fallback-3",
    title: "Dark Roast",
    desc: "深夜咖啡館牽扯出連續失蹤案。每一杯咖啡背後都有交易，每位客人都可能是兇手。",
    poster: "assets/poster3.png",
    genre: ["犯罪片", "懸疑"],
    mood: ["壓迫感", "雨夜", "黑色幽默"],
    mainScene: ["咖啡館", "城市街道"],
    subScene: ["深夜", "雨中"],
    year: "2026",
    duration: "1 小時 46 分",
    trailer: ""
  },
  {
    id: "fallback-4",
    title: "Last Semester",
    desc: "大學最後一學期，一群學生面對畢業、夢想與分離，在最後一次專題中找到未來方向。",
    poster: "assets/poster4.png",
    genre: ["青春片"],
    mood: ["成長", "懷舊", "不捨"],
    mainScene: ["校園", "秋天"],
    subScene: ["教室", "畢業季"],
    year: "2025",
    duration: "1 小時 52 分",
    trailer: ""
  },
  {
    id: "fallback-5",
    title: "Sunset Letters",
    desc: "兩位陌生人因一封寄錯的信而相遇，在夕陽與海岸城市之間，重新相信愛情。",
    poster: "assets/poster5.png",
    genre: ["愛情片"],
    mood: ["浪漫", "溫柔", "夕陽感"],
    mainScene: ["海邊", "老街"],
    subScene: ["黃昏", "城市"],
    year: "2025",
    duration: "1 小時 49 分",
    trailer: ""
  },
  {
    id: "fallback-6",
    title: "Echoes of Tomorrow",
    desc: "在記憶可以被演算法重建的未來，一名研究員發現 AI 保存的不只是資料，而是人類選擇遺忘的真相。",
    poster: "assets/poster6.png",
    genre: ["科幻片"],
    mood: ["未來感", "疏離", "冷調"],
    mainScene: ["未來城市", "實驗室"],
    subScene: ["資料中心", "夜景"],
    year: "2026",
    duration: "2 小時 10 分",
    trailer: ""
  },
  {
    id: "fallback-7",
    title: "Hollow Frame",
    desc: "一名攝影師在老屋中發現每張照片都會出現不存在的人影，他越接近真相就越分不清現實。",
    poster: "assets/poster7.png",
    genre: ["懸疑"],
    mood: ["詭異", "心理壓迫", "孤獨"],
    mainScene: ["老屋", "暗房"],
    subScene: ["鏡子", "相片"],
    year: "2026",
    duration: "1 小時 55 分",
    trailer: ""
  }
];

const TAG_KIND_RULES = {
  mood: ["孤獨", "療癒", "浪漫", "放鬆", "歡樂", "壓迫", "不安", "溫柔", "懷舊", "熱血", "空虛", "疏離", "感人", "悲傷", "焦慮", "沉重", "自由", "安靜", "悵然", "心碎", "陰鬱", "愉快", "舒服", "夢幻", "治癒", "致鬱", "恐懼", "孤單", "寂寞", "失落", "希望"],
  atmosphere: ["深夜", "雨夜", "夕陽", "冷調", "暖色", "迷幻", "黑色幽默", "未來感", "復古", "慢節奏", "海風", "詭異", "神秘", "寧靜", "末日", "霓虹", "夜晚", "夏天", "冬天", "灰暗", "明亮"],
  scene: ["校園", "海邊", "小鎮", "城市", "老屋", "咖啡館", "醫院", "森林", "實驗室", "公路", "夜市", "辦公室", "家庭", "港口", "山區", "雨中", "餐廳", "酒吧", "房間", "車站"],
  genre: ["恐怖", "愛情", "科幻", "犯罪", "喜劇", "動作", "劇情", "動畫", "紀錄", "懸疑", "驚悚", "青春", "冒險"]
};

/*
  探索頁熱門分類的同義標籤。
  FilmDB 中常會出現「愛情片／浪漫喜劇」、「警匪／劫盜」等複合寫法，
  所以分類不能只靠按鈕上的兩個字做完全比對。
*/
const CATEGORY_RULES = {
  "喜劇": ["喜劇", "搞笑", "幽默", "歡樂", "爆笑", "荒謬", "荒唐", "惡搞", "無厘頭", "鬧劇", "詼諧", "黑色幽默", "輕鬆", "comedy"],
  "愛情": ["愛情", "浪漫", "戀愛", "愛戀", "戀情", "情侶", "婚姻", "心動", "甜蜜", "虐戀", "禁忌之戀", "情感糾葛", "關係探索", "romance"],
  "驚悚": ["驚悚", "心理驚悚", "驚險", "緊張", "追殺", "逃亡", "逃生", "追捕", "高壓", "危險", "生存戰", "倒數計時", "綁架", "thriller"],
  "科幻": ["科幻", "未來", "太空", "宇宙", "外星", "機器人", "機甲", "人工智慧", "虛擬實境", "高科技", "時空", "時間旅行", "時空旅行", "多元宇宙", "多重宇宙", "sci-fi", "scifi"],
  "動作": ["動作", "戰鬥", "武打", "武術", "武俠", "功夫", "格鬥", "槍戰", "爆破", "特務", "間諜", "諜報", "警匪", "英雄", "超級英雄", "追逐", "救援", "復仇", "賽車", "action"],
  "動畫": ["動畫", "卡通", "動漫", "擬人化", "動物主角", "童趣", "親子動畫", "3d動畫", "animation", "anime", "pixar"],
  "劇情": ["劇情", "人生", "家庭", "成長", "勵志", "人性", "親情", "友情", "職場", "女性視角", "社會寫實", "傳記", "文學", "政治", "救贖", "drama"],
  "懸疑": ["懸疑", "推理", "謎團", "偵探", "偵查", "調查", "解謎", "神秘", "命案", "懸案", "陰謀", "目擊者", "法醫", "燒腦", "真相", "mystery"],
  "恐怖": ["恐怖", "鬼片", "鬼屋", "鬼怪", "鬼魂", "靈異", "超自然恐怖", "詛咒", "惡魔", "惡靈", "驅魔", "喪屍", "活屍", "血腥", "怪獸", "怪物", "食人", "陰森", "horror"],
  "犯罪": ["犯罪", "黑幫", "幫派", "警匪", "警察", "警方", "毒梟", "毒販", "盜竊", "劫盜", "劫案", "竊賊", "謀殺", "命案", "監獄", "crime"],
  "冒險": ["冒險", "探險", "探索", "旅程", "旅行", "公路電影", "生存", "漂流", "尋寶", "考古", "奇遇", "遺跡", "英雄旅程", "adventure"],
  "奇幻": ["奇幻", "魔法", "魔幻", "精靈", "神話", "童話", "神燈", "異世界", "異空間", "靈魂出竅", "黑暗奇幻", "fantasy"],
  "家庭": ["家庭", "家庭向", "家庭電影", "親子", "親情", "家人", "父子", "母愛", "姐妹", "溫馨", "童趣", "闔家", "兒童", "社區生活", "family"],
  "戰爭": ["戰爭", "戰場", "戰役", "軍事", "軍隊", "軍營", "士兵", "戰俘", "軍官", "核武", "war"],
  "歷史": ["歷史", "歷史劇", "時代劇", "時代", "傳記", "古裝", "古羅馬", "三國", "宮廷", "戒嚴", "真實事件改編", "history"],
  "音樂": ["音樂", "音樂劇", "歌舞", "歌舞劇", "合唱團", "歌手", "樂團", "樂器", "歌曲", "舞蹈", "演唱", "舞台", "表演", "偶像", "music"]
};

const KIND_META = {
  mood: { label: "情緒", icon: "♡", colors: ["#9b5cff", "#f06ba7"], glow: "rgba(240,107,167,0.45)" },
  atmosphere: { label: "氛圍", icon: "☾", colors: ["#406dff", "#7d5cff"], glow: "rgba(79,140,255,0.42)" },
  scene: { label: "場景", icon: "⌂", colors: ["#1eaeb8", "#6ccf91"], glow: "rgba(87,211,218,0.38)" },
  genre: { label: "類型", icon: "✦", colors: ["#dc633a", "#e8b553"], glow: "rgba(232,181,83,0.42)" }
};

const BUBBLE_LIMIT = 10;
const BUBBLE_SIZE = 92;

/*
  展覽模式（刮刮卡標籤版）
  - 標籤來源固定為客戶提供的《刮刮卡標籤》PDF
  - PDF 原始共 120 個欄位；氛圍「神秘」重複一次，因此同類別去重後為 119 個分類標籤項目
  - 每次顯示 10 個
  - 連續 4 組共 40 個可見標籤不重複
  - 第 4 組結束後重新洗牌，開始下一輪
  - 每組：2 類型 + 3 情緒 + 3 氛圍 + 2 場景
*/
const BUBBLE_MODE_KEY = "moodluma-bubble-mode";
const EXHIBITION_ROUND_COUNT = 4;

/*
  展覽模式｜固定四輪

  固定循環：
  第 1 輪 → 第 2 輪 → 第 3 輪 → 第 4 輪 → 第 1 輪 → ...

  重點：
  - 不再每四輪重新隨機抽標籤。
  - 四輪內容完全固定。
  - 同一輪再次出現時，陣列順序也固定，
    因此標籤、類別顏色、圓圈位置都會一樣。
  - 每輪 10 顆：
    2 類型 + 3 情緒 + 3 氛圍 + 2 場景。
*/
const EXHIBITION_FIXED_ROUNDS = [
  [
    { tag: "動作", kind: "genre", score: 1 },
    { tag: "懸疑", kind: "genre", score: 1 },

    { tag: "緊張", kind: "mood", score: 1 },
    { tag: "絕望", kind: "mood", score: 1 },
    { tag: "刺激", kind: "mood", score: 1 },

    { tag: "神秘", kind: "atmosphere", score: 1 },
    { tag: "陰森", kind: "atmosphere", score: 1 },
    { tag: "明亮", kind: "atmosphere", score: 1 },

    { tag: "辦公室", kind: "scene", score: 1 },
    { tag: "森林", kind: "scene", score: 1 }
  ],
  [
    { tag: "喜劇", kind: "genre", score: 1 },
    { tag: "家庭", kind: "genre", score: 1 },

    { tag: "焦慮", kind: "mood", score: 1 },
    { tag: "感動", kind: "mood", score: 1 },
    { tag: "希望", kind: "mood", score: 1 },

    { tag: "黑暗", kind: "atmosphere", score: 1 },
    { tag: "夢幻", kind: "atmosphere", score: 1 },
    { tag: "復古", kind: "atmosphere", score: 1 },

    { tag: "餐廳", kind: "scene", score: 1 },
    { tag: "醫院", kind: "scene", score: 1 }
  ],
  [
    { tag: "冒險", kind: "genre", score: 1 },
    { tag: "恐怖", kind: "genre", score: 1 },

    { tag: "恐懼", kind: "mood", score: 1 },
    { tag: "壓抑", kind: "mood", score: 1 },
    { tag: "溫馨", kind: "mood", score: 1 },

    { tag: "寫實", kind: "atmosphere", score: 1 },
    { tag: "危險", kind: "atmosphere", score: 1 },
    { tag: "奇幻", kind: "atmosphere", score: 1 },

    { tag: "停車場", kind: "scene", score: 1 },
    { tag: "公園", kind: "scene", score: 1 }
  ],
  [
    { tag: "犯罪", kind: "genre", score: 1 },
    { tag: "愛情", kind: "genre", score: 1 },

    { tag: "憤怒", kind: "mood", score: 1 },
    { tag: "不安", kind: "mood", score: 1 },
    { tag: "興奮", kind: "mood", score: 1 },

    { tag: "溫暖", kind: "atmosphere", score: 1 },
    { tag: "混亂", kind: "atmosphere", score: 1 },
    { tag: "華麗", kind: "atmosphere", score: 1 },

    { tag: "住宅", kind: "scene", score: 1 },
    { tag: "地下室", kind: "scene", score: 1 }
  ]
];

let bubbleMode = localStorage.getItem(BUBBLE_MODE_KEY) === "exhibition"
  ? "exhibition"
  : "normal";
let exhibitionRounds = [];
let exhibitionRoundIndex = 0;
const BUBBLE_COLOR_PALETTE = [
  { colors: ["#F08A3E", "#F5C04E"], glow: "rgba(245,192,78,0.42)" },
  { colors: ["#B45CFF", "#EA6FCB"], glow: "rgba(234,111,203,0.42)" },
  { colors: ["#4F6CFF", "#6C8CFF"], glow: "rgba(79,108,255,0.42)" },
  { colors: ["#35C6B0", "#5ED39A"], glow: "rgba(53,198,176,0.38)" }
];

let allMovies = [];
let bubbles = [];
let allTagCandidates = [];
let cachedNormalBubbleCandidates = null;
let cachedPopularityMaxViews = null;
let selectedTags = new Map();
let searchKeyword = "";
let viewCounts = loadViews();
let feedbacks = loadFeedbacks();
let currentModalMovie = null;
let groupMode = false;
let groupMembers = loadGroupMembers();
let activeMemberId = groupMembers[0]?.id || null;
let groupVotes = loadGroupVotes();
let authMode = "login";
let libraryMode = "favorites";
let pendingMovie = null;
let currentTab = "全部收藏";
/** 登入帳號的後端個人推薦（push_feed / recommend/me） */
let serverRecommendCards = [];
/** 房間成員各自推薦：{ [memberName]: { cards, source, ... } } */
let memberRecommendByName = {};
let memberRecommendMeta = null;
const DEFAULT_APP_SETTINGS = {
  themeDark: true,
  anim: true,
  cardSize: "中",
  prefPop: false,
  prefNiche: false,
  noHorror: false,
  noSad: false
};

let appSettings = {
  ...DEFAULT_APP_SETTINGS,
  ...loadJson("moodluma_settings", DEFAULT_APP_SETTINGS)
};

function getBubblePaletteByGroup(index, total) {
  const paletteCount = BUBBLE_COLOR_PALETTE.length;
  const baseSize = Math.floor(total / paletteCount);
  const extra = total % paletteCount;

  let start = 0;

  for (let i = 0; i < paletteCount; i++) {
    const groupSize = baseSize + (i < extra ? 1 : 0);
    const end = start + groupSize;

    if (index >= start && index < end) {
      return BUBBLE_COLOR_PALETTE[i];
    }

    start = end;
  }

  return BUBBLE_COLOR_PALETTE[paletteCount - 1];
}

function saveAppSettings() {
  saveJson("moodluma_settings", appSettings);
  scheduleUserStatePush();
}

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindUI();
  allMovies = await loadMoviesFromFilmDB();

  try {
    await initRoomFromServer();
  } catch (e) {
    console.warn("room init fallback", e);
    updateRoomUI();
    groupMembers = loadGroupMembers();
    groupVotes = loadGroupVotes();
    activeMemberId = groupMembers[0]?.id || null;
    ensureDefaultMembers();
  }
  buildBubbleModeInitialState();
  renderMembers();
  renderGroupTags();
  renderRoleOptions();
  renderSelectedTags();
  renderRecommendations();
  renderExploreResults();
  renderCollection();
  updateAuthUI();
  updateMemberStats();
  if (getCurrentUser() && localStorage.getItem(AUTH_TOKEN_KEY)) {
    syncUserStateFromCloud()
      .then(() => refreshPersonalRecommend({ publish: true }))
      .catch((e) => console.warn("init sync failed", e));
  }
  window.addEventListener("resize", debounceBubbleLayout);
}

let bubbleResizeTimer = null;
function debounceBubbleLayout() {
  clearTimeout(bubbleResizeTimer);
  bubbleResizeTimer = setTimeout(() => {
    if (bubbles.length) layoutBubbles();
  }, 120);
}

function bindUI() {
  $("searchBtn").addEventListener("click", handleSearch);
  $("searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleSearch();
  });

  $("resetBtn").addEventListener("click", () => {
    selectedTags.clear();
    searchKeyword = "";
    $("searchInput").value = "";
    bubbles.forEach((b) => {
      b.weight = 0;
      b.el.classList.remove("selected");
    });
    renderSelectedTags();
    renderRecommendations();
  });

  $("normalModeBtn")?.addEventListener("click", () => {
    switchBubbleMode("normal");
  });

  $("exhibitionModeBtn")?.addEventListener("click", () => {
    switchBubbleMode("exhibition");
  });

  $("shuffleBtn").addEventListener("click", () => {
    if (bubbleMode === "exhibition") {
      showNextExhibitionRound();
      return;
    }

    if (!allTagCandidates || allTagCandidates.length === 0) return;

    const currentTags = bubbles.map(b => b.tag);
    const newSelected = pickBalancedTags(allTagCandidates, currentTags);
    createBubbles(newSelected);
  });

  $("rerollBtn").addEventListener("click", () => {
    const tags = bubbles.map(b => b.tag);
    if (!tags.length) return;
    const randomTag = tags[Math.floor(Math.random() * tags.length)];
    addSelectedTag(randomTag, 0.72, "random");
    renderRecommendations();
  });

  $("viewAllBtn").addEventListener("click", () => renderRecommendations(true));

  $("modalClose").addEventListener("click", closeModal);
  $("modalBackdrop").addEventListener("click", closeModal);

  $("feedbackTemperature")?.addEventListener("input", (e) => {
    updateTemperaturePreview(Number(e.target.value));
  });

  $("submitTempFeedback")?.addEventListener("click", () => {
    const value = Number($("feedbackTemperature")?.value || 50);
    setTemperatureFeedback(value);
  });

  $("trailerLink")?.addEventListener("click", () => {
    if (!currentModalMovie) return;
    markTrailerWatched(currentModalMovie);
    updateFeedbackUI(currentModalMovie);
  });

  $("focusMemberInputBtn")?.addEventListener("click", () => {
  $("memberNameInput")?.focus();
});

  $("addMemberBtn")?.addEventListener("click", addMemberFromInput);
  $("memberNameInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addMemberFromInput();
  });

  $("groupModeBtn")?.addEventListener("click", () => {
    groupMode = !groupMode;
    $("groupModeBtn").classList.toggle("active", groupMode);
    $("groupModeBtn").textContent = groupMode ? "多人模式已開啟" : "開啟多人模式";
    renderRecommendations();
  });
  $("roomMemberRecommendBtn")?.addEventListener("click", () => {
    refreshRoomMemberRecommends({ publish: true }).catch((e) => {
      console.warn("room member recommend failed", e);
      alert(e.message || "產生成員推薦失敗");
    });
  });

  $("newRoomBtn")?.addEventListener("click", async () => {
    try {
      stopRoomPoll();
      const room = await apiRoomCreate("Moodluma");
      groupMembers = [];
      groupVotes = {};
      activeMemberId = null;
      localStorage.setItem(ROOM_KEY, room.code);
      updateRoomUI();
      saveGroupMembers();
      saveGroupVotes();
      startRoomPoll();
      renderMembers();
      renderGroupTags();
      alert(`已建立新房間：${formatRoomCodeDisplay(room.code)}`);
    } catch (e) {
      alert(e.message || "建立房間失敗");
    }
  });

  $("joinRoomBtn")?.addEventListener("click", () => {
    const code = $("joinRoomInput")?.value || "";
    if (!code.trim()) {
      alert("請輸入房間代碼。");
      return;
    }
    setCurrentRoomCode(code);
  });

  $("joinRoomInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const code = $("joinRoomInput")?.value || "";
      if (!code.trim()) {
        alert("請輸入房間代碼。");
        return;
      }
      setCurrentRoomCode(code);
    }
  });

  // 點選角色圖片，套用到目前選中的成員
  document.querySelectorAll(".role-option").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!activeMemberId) return;

      const member = groupMembers.find(m => m.id === activeMemberId);
      if (!member) return;

      member.role = btn.dataset.role;

      saveGroupMembers();
      renderMembers();
      renderRoleOptions();
    });
  });

  $("groupWantBtn")?.addEventListener("click", () => setGroupVote("want"));
  $("groupNopeBtn")?.addEventListener("click", () => setGroupVote("nope"));

  $("favoriteBtn")?.addEventListener("click", () => {
    if (!currentModalMovie) return;
    toggleFavorite(currentModalMovie);
    updateFavoriteUI(currentModalMovie);
    updateMemberStats();
    renderCollection();
    renderExploreResults($("exploreSearchInput")?.value || "");
    renderRecommendations();
  });

  $("historyBtn")?.addEventListener("click", () => openLibrary("history"));
  bindPageNavigation();
  bindExploreUI();
  bindCollectionUI();
  bindSettingsUI();

  $("loginBtn")?.addEventListener("click", () => openAuth("login"));
  $("registerBtn")?.addEventListener("click", () => openAuth("register"));
  $("memberSpaceBtn")?.addEventListener("click", openMemberSpace);
  $("memberLoginFromSpace")?.addEventListener("click", () => {
    closeMemberSpace();
    openAuth("login");
  });
  $("logoutBtn")?.addEventListener("click", logoutUser);

  $("authClose")?.addEventListener("click", closeAuth);
  $("authBackdrop")?.addEventListener("click", closeAuth);
  $("authLoginTab")?.addEventListener("click", () => setAuthMode("login"));
  $("authRegisterTab")?.addEventListener("click", () => setAuthMode("register"));
  $("authSubmit")?.addEventListener("click", handleAuthSubmit);
  $("forgotPasswordBtn")?.addEventListener("click", openForgotPassword);
  $("forgotPasswordClose")?.addEventListener("click", closeForgotPassword);
  $("forgotPasswordBackdrop")?.addEventListener("click", closeForgotPassword);
  $("backToLoginBtn")?.addEventListener("click", () => {
    closeForgotPassword();
    openAuth("login");
  });
  $("resetPasswordSubmit")?.addEventListener("click", handlePasswordReset);
  $("resetConfirmPassword")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handlePasswordReset();
  });
  $("authPassword")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleAuthSubmit();
  });

  $("libraryClose")?.addEventListener("click", closeLibrary);
  $("libraryBackdrop")?.addEventListener("click", closeLibrary);
  $("libraryClearBtn")?.addEventListener("click", clearCurrentLibrary);

  $("memberClose")?.addEventListener("click", closeMemberSpace);
  $("memberBackdrop")?.addEventListener("click", closeMemberSpace);
  $("memberHistoryBtn")?.addEventListener("click", () => openLibrary("history"));
  $("memberFavoriteBtn")?.addEventListener("click", () => openLibrary("favorites"));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModal();
      closeAuth();
      closeLibrary();
      closeMemberSpace();
      closeCollectionChoice();
    }
  });
}

function fetchWithTimeout(url, options = {}, timeoutMs = 3500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(timer));
}

async function loadMoviesFromFilmDB() {
  $("dbStatus").textContent = "正在連接你的 FilmDB 資料庫...";

  for (const url of API_CANDIDATES) {
    try {
      const res = await fetchWithTimeout(url, {
        cache: "no-store",
        mode: "cors"
      });

      if (!res.ok) continue;

      const contentType = res.headers.get("content-type") || "";
      let list = [];

      if (contentType.includes("application/json")) {
        const data = await res.json();
        list = normalizeMovieList(data);
      } else {
        const text = await res.text();
        const jsonData = extractJsonFromText(text);
        if (jsonData) {
          list = normalizeMovieList(jsonData);
        }

        if (!list.length) {
          list = parseMoviesFromHtml(text, url);
        }
      }

      if (list.length) {
        $("dbStatus").textContent = `已連接 FilmDB：成功讀取 ${list.length} 部電影，圓圈與搜尋皆由資料庫生成。`;
        return list;
      }
    } catch (err) {
      console.warn("FilmDB 讀取失敗：", url, err);
    }
  }

  $("dbStatus").textContent = "FilmDB 目前無法由瀏覽器直接讀取，可能是 API 路徑或 CORS 尚未開放。現在先使用本地示範資料。";
  return FALLBACK_MOVIES.map((m, i) => normalizeMovie(m, i));
}

function extractJsonFromText(text) {
  const trimmed = text.trim();

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.parse(trimmed);
    } catch {}
  }

  const nextMatch = text.match(/<script[^>]*id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i);
  if (nextMatch) {
    try {
      return JSON.parse(nextMatch[1]);
    } catch {}
  }

  const windowDataMatch = text.match(/window\.__(?:DATA|MOVIES|FILMS)__\s*=\s*([\s\S]*?);<\/script>/i);
  if (windowDataMatch) {
    try {
      return JSON.parse(windowDataMatch[1]);
    } catch {}
  }

  const arrayMatch = text.match(/(\[\s*\{[\s\S]*?\}\s*\])/);
  if (arrayMatch) {
    try {
      return JSON.parse(arrayMatch[1]);
    } catch {}
  }

  return null;
}


function getBackgroundImageUrl(el) {
  const style = el.getAttribute("style") || "";
  const m = style.match(/background(?:-image)?\s*:\s*url\(["']?([^"')]+)["']?\)/i);
  return m ? m[1] : "";
}

function parseMoviesFromHtml(html, sourceUrl) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const movies = [];
  const tables = [...doc.querySelectorAll("table")];
  for (const table of tables) {
    const headers = [...table.querySelectorAll("thead th, tr:first-child th, tr:first-child td")]
      .map(th => th.textContent.trim());

    const rows = [...table.querySelectorAll("tbody tr")];
    const targetRows = rows.length ? rows : [...table.querySelectorAll("tr")].slice(1);

    targetRows.forEach((row, idx) => {
      const cells = [...row.querySelectorAll("td")];
      if (!cells.length) return;

      const raw = {};
      cells.forEach((cell, i) => {
        const key = headers[i] || `欄位${i + 1}`;
        raw[key] = cell.textContent.trim();

        const img = cell.querySelector("img");
        if (img?.src) raw["海報"] = absolutize(img.getAttribute("src"), sourceUrl);

        const bgImage = getBackgroundImageUrl(cell);
        if (!raw["海報"] && bgImage) raw["海報"] = absolutize(bgImage, sourceUrl);

        const link = cell.querySelector("a[href]");
        if (link?.href && /youtube|youtu\.be|trailer|watch/i.test(link.href)) {
          raw["預告片"] = link.href;
        }
      });

      movies.push(normalizeMovie(raw, idx));
    });
  }

  if (!movies.length) {
    const cards = [...doc.querySelectorAll("[class*='card'], [class*='movie'], [class*='film'], article")];
    cards.forEach((card, idx) => {
      const titleEl = card.querySelector("h1,h2,h3,h4,[class*='title'],[class*='name']");
      if (!titleEl) return;

      const img = card.querySelector("img");
      const bgImage = getBackgroundImageUrl(card) || [...card.querySelectorAll("[style]")].map(getBackgroundImageUrl).find(Boolean);
      const link = [...card.querySelectorAll("a[href]")].find(a => /youtube|youtu\.be|trailer|watch/i.test(a.href));

      const text = card.textContent.trim().replace(/\s+/g, " ");
      const raw = {
        "片名": titleEl.textContent.trim(),
        "簡介": text,
        "海報": img ? absolutize(img.getAttribute("src"), sourceUrl) : (bgImage ? absolutize(bgImage, sourceUrl) : ""),
        "預告片": link ? link.href : ""
      };

      movies.push(normalizeMovie(raw, idx));
    });
  }

  return movies.filter(m => m.title);
}

function absolutize(url, baseUrl) {
  if (!url) return "";
  try {
    return new URL(url, baseUrl).href;
  } catch {
    return url;
  }
}

function normalizeMovieList(data) {
  let arr = [];

  if (Array.isArray(data)) arr = data;
  else if (Array.isArray(data.movies)) arr = data.movies;
  else if (Array.isArray(data.films)) arr = data.films;
  else if (Array.isArray(data.data)) arr = data.data;
  else if (Array.isArray(data.items)) arr = data.items;
  else if (Array.isArray(data.results)) arr = data.results;
  else if (data.props?.pageProps) {
    const p = data.props.pageProps;
    arr = p.movies || p.films || p.data || p.items || [];
  }

  return arr.map((item, idx) => normalizeMovie(item, idx)).filter(m => m.title);
}


function getYoutubeIdFromUrl(url) {
  if (!url) return "";
  const s = String(url).trim();

  const patterns = [
    /youtu\.be\/([a-zA-Z0-9_-]{6,})/,
    /youtube\.com\/watch\?v=([a-zA-Z0-9_-]{6,})/,
    /youtube\.com\/embed\/([a-zA-Z0-9_-]{6,})/,
    /youtube\.com\/shorts\/([a-zA-Z0-9_-]{6,})/,
    /\/vi\/([a-zA-Z0-9_-]{6,})\//
  ];

  for (const p of patterns) {
    const m = s.match(p);
    if (m) return m[1];
  }

  if (/^[a-zA-Z0-9_-]{8,}$/.test(s) && !s.includes("/") && !s.includes(".")) return s;

  return "";
}

function youtubeThumb(videoId, quality = "mqdefault") {
  if (!videoId) return "";
  return `https://img.youtube.com/vi/${videoId}/${quality}.jpg`;
}

function pickPosterFromMovie(raw, trailer, poster, idx) {
  if (poster) return poster;

  const getRaw = (keys) => {
    for (const key of keys) {
      if (raw && raw[key]) return raw[key];
    }
    const rawKeys = Object.keys(raw || {});
    for (const wanted of keys) {
      const found = rawKeys.find(k => normalizeKey(k) === normalizeKey(wanted));
      if (found && raw[found]) return raw[found];
    }
    return "";
  };

  const youtubeIdValue = getRaw(FIELD_MAP.youtubeId || []);
  const idFromField = getYoutubeIdFromUrl(youtubeIdValue);
  const idFromTrailer = getYoutubeIdFromUrl(trailer);

  const videoId = idFromField || idFromTrailer;
  if (videoId) return youtubeThumb(videoId, "mqdefault");

  return `assets/poster${(idx % 7) + 1}.png`;
}

function normalizeMovie(raw, idx = 0) {
  const get = (type) => {
    for (const key of FIELD_MAP[type]) {
      if (raw && raw[key] !== undefined && raw[key] !== null && raw[key] !== "") return raw[key];
    }

    // 支援大小寫或空白不同的欄位
    const rawKeys = Object.keys(raw || {});
    for (const wanted of FIELD_MAP[type]) {
      const found = rawKeys.find(k => normalizeKey(k) === normalizeKey(wanted));
      if (found && raw[found] !== undefined && raw[found] !== null && raw[found] !== "") return raw[found];
    }

    return "";
  };

  const title = String(get("title") || `未命名電影 ${idx + 1}`).trim();
  const id = raw.id || raw._id || raw.uuid || slug(title);
  const trailer = normalizeUrl(get("trailer"));
  const rawPoster = normalizeUrl(get("poster"));
  const poster = normalizeUrl(pickPosterFromMovie(raw, trailer, rawPoster, idx));

  return {
    id,
    title,
    desc: String(get("desc") || "目前資料庫尚未提供完整簡介。"),
    poster,
    trailer,
    year: String(get("year") || ""),
    duration: String(get("duration") || ""),
    views: Number(get("views") || 0),
    actors: String(get("actors") || ""),
    genre: toArray(get("genre")),
    mood: toArray(get("mood")),
    mainScene: toArray(get("mainScene")),
    subScene: toArray(get("subScene")),
    keywords: toArray(get("keywords")),
    raw
  };
}

function normalizeKey(s) {
  return String(s).toLowerCase().replace(/\s|_|-|\/|／|：|:/g, "");
}

function normalizeUrl(url) {
  if (!url) return "";
  const s = String(url).trim();
  if (!s) return "";
  if (s.startsWith("http")) return s;
  if (s.startsWith("/")) return FILMDB_BASE + s;
  return s;
}

function toArray(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(cleanTag).filter(Boolean);
  if (typeof value === "object") return Object.values(value).flatMap(toArray);
  return String(value)
    .split(/[,，、|/／\n;；]+/)
    .map(cleanTag)
    .filter(Boolean);
}

function cleanTag(s) {
  return String(s).trim().replace(/^#/, "").replace(/\s+/g, " ");
}

function getTagIdentity(tag) {
  let key = cleanTag(tag)
    .toLowerCase()
    .replace(/[\s_\-—–・·,，、|/／;；:：()（）\[\]【】]/g, "")
    .replace(/(?:電影|影片|片)$/u, "");

  // 常見資料會同時放入「孤獨」與「孤獨感」，視覺上應視為同一個標籤。
  if (key.length > 2 && key.endsWith("感")) key = key.slice(0, -1);

  return key;
}

function slug(s) {
  return String(s).toLowerCase().replace(/[^\w\u4e00-\u9fa5]+/g, "-");
}


function shuffleCopy(items) {
  const list = [...items];

  for (let i = list.length - 1; i > 0; i -= 1) {
    const j = Math.floor(randomUnit() * (i + 1));
    [list[i], list[j]] = [list[j], list[i]];
  }

  return list;
}

function buildExhibitionRounds() {
  exhibitionRounds = EXHIBITION_FIXED_ROUNDS.map(round =>
    round.map(item => ({ ...item }))
  );

  exhibitionRoundIndex = 0;
}

function renderBubbleModeUI() {
  const normalBtn = $("normalModeBtn");
  const exhibitionBtn = $("exhibitionModeBtn");
  const roundBadge = $("exhibitionRoundBadge");
  const normalMovieCountBadge = $("normalMovieCountBadge");
  const title = $("moodStageTitle");
  const desc = $("moodStageDesc");
  const shuffleBtn = $("shuffleBtn");

  const isExhibition = bubbleMode === "exhibition";

  normalBtn?.classList.toggle("active", !isExhibition);
  exhibitionBtn?.classList.toggle("active", isExhibition);
  normalBtn?.setAttribute("aria-pressed", String(!isExhibition));
  exhibitionBtn?.setAttribute("aria-pressed", String(isExhibition));

  if (title) {
    title.textContent = isExhibition
      ? "展覽模式｜今天想看什麼感覺？"
      : "今天想看什麼感覺的電影？";
  }

  if (desc) {
    desc.textContent = isExhibition
      ? "固定 4 組標籤循環；每次刷新換下一組，第 4 組後回到完全相同的第 1 組。"
      : `一般模式由資料庫標籤動態產生；目前資料庫共 ${allMovies.length.toLocaleString("zh-TW")} 部電影。`;
  }

  if (roundBadge) {
    roundBadge.hidden = !isExhibition;
    roundBadge.textContent = `固定循環 ${exhibitionRoundIndex + 1} / ${EXHIBITION_ROUND_COUNT}`;
  }

  if (normalMovieCountBadge) {
    normalMovieCountBadge.hidden = isExhibition;
    normalMovieCountBadge.textContent =
      `目前資料庫 ${allMovies.length.toLocaleString("zh-TW")} 部電影`;
  }

  if (shuffleBtn) {
    shuffleBtn.textContent = "⟳ 換個排列";
  }

  document.body.classList.toggle("exhibition-mode", isExhibition);
}

function clearBubbleSelectionForModeSwitch() {
  selectedTags.clear();
  searchKeyword = "";

  const searchInput = $("searchInput");
  if (searchInput) searchInput.value = "";

  bubbles.forEach(bubble => {
    bubble.weight = 0;
    bubble.el?.classList.remove("selected");
  });

  renderSelectedTags();
}

function showExhibitionRound(roundIndex = exhibitionRoundIndex) {
  if (!exhibitionRounds.length) buildExhibitionRounds();

  exhibitionRoundIndex = Math.max(
    0,
    Math.min(EXHIBITION_ROUND_COUNT - 1, Number(roundIndex) || 0)
  );

  createBubbles(exhibitionRounds[exhibitionRoundIndex]);
  renderBubbleModeUI();
}

function showNextExhibitionRound() {
  if (!exhibitionRounds.length) {
    buildExhibitionRounds();
  }

  exhibitionRoundIndex =
    (exhibitionRoundIndex + 1) % EXHIBITION_ROUND_COUNT;

  showExhibitionRound(exhibitionRoundIndex);
}

function switchBubbleMode(nextMode) {
  const normalizedMode = nextMode === "exhibition" ? "exhibition" : "normal";

  if (bubbleMode === normalizedMode) {
    renderBubbleModeUI();
    return;
  }

  bubbleMode = normalizedMode;
  localStorage.setItem(BUBBLE_MODE_KEY, bubbleMode);
  scheduleUserStatePush();
  clearBubbleSelectionForModeSwitch();

  if (bubbleMode === "exhibition") {
    buildExhibitionRounds();
    showExhibitionRound(0);
  } else {
    buildDynamicBubbles();
    renderBubbleModeUI();
  }

  renderRecommendations();
}

function buildBubbleModeInitialState() {
  if (bubbleMode === "exhibition") {
    buildExhibitionRounds();
    showExhibitionRound(0);
    return;
  }

  buildDynamicBubbles();
  renderBubbleModeUI();
}

function buildDynamicBubbles() {
  // 資料庫本身沒有改變時，候選標籤統計只需要做一次。
  if (cachedNormalBubbleCandidates?.length) {
    allTagCandidates = cachedNormalBubbleCandidates;
    const selected = pickBalancedTags(allTagCandidates, []);
    createBubbles(selected);
    return;
  }

  const counts = new Map();

  allMovies.forEach(movie => {
    const fieldGroups = [
      { list: movie.mood, base: 5.2 },
      { list: movie.genre, base: 2.2 },
      { list: movie.mainScene, base: 3.1 },
      { list: movie.subScene, base: 2.2 },
      { list: movie.keywords, base: 1.8 }
    ];

    fieldGroups.forEach(({ list, base }) => {
      (list || []).forEach(tag => {
        const clean = cleanTag(tag);
        const tagKey = getTagIdentity(clean);
        if (!tagKey) return;

        const kind = classifyTag(clean);
        const prev = counts.get(tagKey) || { tag: clean, score: 0, kind, count: 0 };
        prev.score += base + (kind === "mood" ? 1.4 : 0);
        prev.count += 1;
        prev.kind = kind;
        // 同時有「愛情」與「愛情片」時，畫面保留較精簡的名稱。
        if (clean.length < prev.tag.length) prev.tag = clean;
        counts.set(tagKey, prev);
      });
    });
  });

  let candidates = [...counts.values()];

  // 若資料庫標籤太少，補一些偏「感受型」的圓圈，避免畫面空。
  if (candidates.length < 10) {
    const fallbackTags = [
      ["孤獨", "mood"], ["療癒", "mood"], ["浪漫", "mood"], ["壓迫感", "mood"], ["放空", "mood"],
      ["深夜感", "atmosphere"], ["雨夜", "atmosphere"], ["夕陽感", "atmosphere"], ["冷調", "atmosphere"],
      ["校園", "scene"], ["海邊", "scene"], ["咖啡館", "scene"], ["老屋", "scene"],
      ["恐怖片", "genre"], ["愛情片", "genre"]
    ];
    fallbackTags.forEach(([tag, kind]) => {
      if (!counts.has(getTagIdentity(tag))) candidates.push({ tag, score: 1, kind, count: 1 });
    });
  }

  cachedNormalBubbleCandidates = candidates;
  allTagCandidates = cachedNormalBubbleCandidates;

  const selected = pickBalancedTags(allTagCandidates, []);
  createBubbles(selected);
}

function classifyTag(tag) {
  const t = String(tag);
  for (const [kind, words] of Object.entries(TAG_KIND_RULES)) {
    if (words.some(w => t.includes(w) || w.includes(t))) return kind;
  }
  return "mood";
}

const recentBubbleSetSignatures = [];
const recentNormalBubbleTagRounds = [];
const NORMAL_BUBBLE_HISTORY_ROUNDS = 4;

function randomUnit() {
  if (globalThis.crypto?.getRandomValues) {
    const buffer = new Uint32Array(1);
    globalThis.crypto.getRandomValues(buffer);
    return (buffer[0] + 1) / 4294967297;
  }
  return Math.random();
}

function weightedRandomSample(items, count, discouragedTags = new Set()) {
  if (!items.length || count <= 0) return [];

  return items
    .map(item => {
      const baseScore = Math.max(0.25, Math.log2(2 + Number(item.score || 0)));
      const repeatPenalty = discouragedTags.has(getTagIdentity(item.tag)) ? 0.06 : 1;
      const weight = Math.max(0.08, baseScore * repeatPenalty);
      const key = Math.pow(randomUnit(), 1 / weight);
      return { item, key };
    })
    .sort((a, b) => b.key - a.key)
    .slice(0, count)
    .map(entry => entry.item);
}

function buildRandomBalancedTagSet(candidates, discouragedTagKeys = new Set(), currentTagKeys = new Set()) {
  const kindOrder = ["genre", "mood", "atmosphere", "scene"];
  const quotas = { genre: 2, mood: 3, atmosphere: 3, scene: 2 };
  const buckets = { mood: [], atmosphere: [], scene: [], genre: [] };

  candidates.forEach(item => {
    const kind = buckets[item.kind] ? item.kind : "mood";
    buckets[kind].push(item);
  });

  const picked = [];
  const seen = new Set();

  const addItems = items => {
    items.forEach(item => {
      const tagKey = getTagIdentity(item.tag);
      if (!tagKey || seen.has(tagKey)) return;
      seen.add(tagKey);
      picked.push(item);
    });
  };

  kindOrder.forEach(kind => {
    const freshItems = buckets[kind].filter(item => !discouragedTagKeys.has(getTagIdentity(item.tag)));
    addItems(weightedRandomSample(freshItems, quotas[kind]));

    let missingCount = quotas[kind] - picked.filter(item => item.kind === kind).length;
    if (missingCount > 0) {
      // 候選池不足時先重用較早輪次的標籤，仍避開畫面上一輪正在顯示的標籤。
      const olderItems = buckets[kind].filter(item => {
        const tagKey = getTagIdentity(item.tag);
        return !seen.has(tagKey) && !currentTagKeys.has(tagKey);
      });
      addItems(weightedRandomSample(olderItems, missingCount, discouragedTagKeys));
    }

    missingCount = quotas[kind] - picked.filter(item => item.kind === kind).length;
    if (missingCount > 0) {
      const currentItems = buckets[kind].filter(item => !seen.has(getTagIdentity(item.tag)));
      addItems(weightedRandomSample(currentItems, missingCount, discouragedTagKeys));
    }
  });

  const freshRemaining = candidates.filter(item => {
    const tagKey = getTagIdentity(item.tag);
    return !seen.has(tagKey) && !discouragedTagKeys.has(tagKey);
  });
  addItems(weightedRandomSample(freshRemaining, BUBBLE_LIMIT - picked.length));

  if (picked.length < BUBBLE_LIMIT) {
    const olderRemaining = candidates.filter(item => {
      const tagKey = getTagIdentity(item.tag);
      return !seen.has(tagKey) && !currentTagKeys.has(tagKey);
    });
    addItems(weightedRandomSample(olderRemaining, BUBBLE_LIMIT - picked.length, discouragedTagKeys));
  }

  if (picked.length < BUBBLE_LIMIT) {
    const repeatedRemaining = candidates.filter(item => !seen.has(getTagIdentity(item.tag)));
    addItems(weightedRandomSample(repeatedRemaining, BUBBLE_LIMIT - picked.length, discouragedTagKeys));
  }

  return picked
    .slice(0, BUBBLE_LIMIT)
    .sort((a, b) => kindOrder.indexOf(a.kind) - kindOrder.indexOf(b.kind));
}

function pickBalancedTags(candidates, excludeTags = []) {
  if (!Array.isArray(candidates) || !candidates.length) return [];

  const currentTagKeys = new Set(excludeTags.map(getTagIdentity).filter(Boolean));
  const recentTagKeys = new Set(
    recentNormalBubbleTagRounds.flatMap(round => [...round])
  );
  const discouragedTagKeys = new Set([...currentTagKeys, ...recentTagKeys]);
  let selected = [];

  for (let attempt = 0; attempt < 12; attempt += 1) {
    const candidateSet = buildRandomBalancedTagSet(candidates, discouragedTagKeys, currentTagKeys);
    const signature = candidateSet
      .map(item => getTagIdentity(item.tag))
      .slice()
      .sort()
      .join("|");

    const changedCount = candidateSet.filter(item => !currentTagKeys.has(getTagIdentity(item.tag))).length;
    const availableFreshCount = candidates.filter(item => !currentTagKeys.has(getTagIdentity(item.tag))).length;
    const minimumChanged = Math.min(candidateSet.length, availableFreshCount, Math.ceil(candidateSet.length * 0.7));
    const recentlyUsed = recentBubbleSetSignatures.includes(signature);

    selected = candidateSet;

    if (!recentlyUsed && changedCount >= minimumChanged) {
      break;
    }
  }

  const selectedSignature = selected
    .map(item => getTagIdentity(item.tag))
    .slice()
    .sort()
    .join("|");

  if (selectedSignature) {
    recentBubbleSetSignatures.push(selectedSignature);
    while (recentBubbleSetSignatures.length > 8) recentBubbleSetSignatures.shift();

    recentNormalBubbleTagRounds.push(
      new Set(selected.map(item => getTagIdentity(item.tag)).filter(Boolean))
    );
    while (recentNormalBubbleTagRounds.length > NORMAL_BUBBLE_HISTORY_ROUNDS) {
      recentNormalBubbleTagRounds.shift();
    }
  }

  return selected;
}

function createBubbles(items) {
  const stage = $("moodStage");
  stage.querySelectorAll(".mood-bubble").forEach(el => el.remove());

  const displayItems = items.slice(0, BUBBLE_LIMIT);

  bubbles = displayItems.map(item => {
    const meta = KIND_META[item.kind] || KIND_META.mood;
    const el = document.createElement("button");
    el.className = "mood-bubble";
    el.style.setProperty("--bubble-a", meta.colors[0]);
    el.style.setProperty("--bubble-b", meta.colors[1]);
    el.style.setProperty("--glow", meta.glow);
    el.innerHTML = `
      <span>
        <div class="icon">${meta.icon}</div>
        <div class="tag">${escapeHtml(item.tag)}</div>
        <div class="kind">${meta.label}</div>
      </span>
    `;
    el.dataset.tag = item.tag;
    el.dataset.kind = item.kind;
    stage.appendChild(el);

    const bubble = { ...item, el, x: 0, y: 0, weight: 0, size: 0 };

    makeDraggable(bubble);
    el.addEventListener("click", () => {
      if (el.classList.contains("dragging")) return;
      addSelectedTag(item.tag, bubble.weight || 0.62, item.kind);
      renderRecommendations();
    });

    return bubble;
  });

  layoutBubbles();
}

function getResponsiveBubbleSize(stageWidth) {
  if (stageWidth <= 340) return 58;
  if (stageWidth <= 380) return 62;
  if (stageWidth <= 430) return 66;
  if (stageWidth <= 520) return 72;
  if (stageWidth <= 700) return 80;
  return BUBBLE_SIZE;
}

function layoutBubbles() {
  const stage = $("moodStage");
  if (!stage || !bubbles.length) return;

  const rect = stage.getBoundingClientRect();
  const cx = rect.width / 2;
  const cy = rect.height / 2;
  const total = bubbles.length;
  const size = getResponsiveBubbleSize(rect.width);
  const maxRadiusX = rect.width / 2 - size / 2 - 10;
  const maxRadiusY = rect.height / 2 - size / 2 - 12;
  const radius = Math.max(
    70,
    Math.min(Math.min(rect.width, rect.height) * 0.39, maxRadiusX, maxRadiusY)
  );

  bubbles.forEach((bubble, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;
    bubble.size = size;
    bubble.x = cx + Math.cos(angle) * radius - size / 2;
    bubble.y = cy + Math.sin(angle) * radius - size / 2;

    bubble.el.style.setProperty("width", `${size}px`, "important");
    bubble.el.style.setProperty("height", `${size}px`, "important");
    bubble.el.style.setProperty("min-width", `${size}px`, "important");
    bubble.el.style.setProperty("min-height", `${size}px`, "important");
    bubble.el.style.setProperty("max-width", `${size}px`, "important");
    bubble.el.style.setProperty("max-height", `${size}px`, "important");
    bubble.el.style.setProperty("transform", "none", "important");

    setBubblePosition(bubble);
    updateBubbleWeight(bubble);
  });
}

let bubbleResizeFrame = 0;
function scheduleBubbleLayout() {
  cancelAnimationFrame(bubbleResizeFrame);
  bubbleResizeFrame = requestAnimationFrame(() => {
    if (bubbles.length) layoutBubbles();
  });
}

window.addEventListener("resize", scheduleBubbleLayout, { passive: true });
window.addEventListener("orientationchange", scheduleBubbleLayout);

function clampBubbleToStage(bubble) {
  const stage = $("moodStage");
  const padding = 8;
  bubble.x = Math.max(padding, Math.min(bubble.x, stage.clientWidth - bubble.size - padding));
  bubble.y = Math.max(padding, Math.min(bubble.y, stage.clientHeight - bubble.size - padding));
}

function setBubblePosition(bubble) {
  bubble.el.style.left = `${bubble.x}px`;
  bubble.el.style.top = `${bubble.y}px`;
}

function makeDraggable(bubble) {
  let startX = 0;
  let startY = 0;
  let originX = 0;
  let originY = 0;
  let moved = false;

  bubble.el.addEventListener("pointerdown", (e) => {
    bubble.el.setPointerCapture(e.pointerId);
    startX = e.clientX;
    startY = e.clientY;
    originX = bubble.x;
    originY = bubble.y;
    moved = false;
    bubble.el.classList.add("dragging");
  });

  bubble.el.addEventListener("pointermove", (e) => {
    if (!bubble.el.classList.contains("dragging")) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    bubble.x = originX + dx;
    bubble.y = originY + dy;
    clampBubbleToStage(bubble);
    setBubblePosition(bubble);
    updateBubbleWeight(bubble);
  });

  const finishDrag = (e) => {
    if (bubble.el.hasPointerCapture?.(e.pointerId)) bubble.el.releasePointerCapture(e.pointerId);
    bubble.el.classList.remove("dragging");
    updateBubbleWeight(bubble);

    if (moved && bubble.weight > 0.34) {
      addSelectedTag(bubble.tag, bubble.weight, bubble.kind);
      renderRecommendations();
    }
  };

  bubble.el.addEventListener("pointerup", finishDrag);
  bubble.el.addEventListener("pointercancel", finishDrag);
}

function updateBubbleWeight(bubble) {
  const stage = $("moodStage");
  const rect = stage.getBoundingClientRect();
  const cx = rect.width / 2;
  const cy = rect.height / 2;
  const bx = bubble.x + bubble.size / 2;
  const by = bubble.y + bubble.size / 2;
  const dist = Math.hypot(bx - cx, by - cy);
  const maxDist = Math.min(rect.width, rect.height) * 0.46;
  bubble.weight = Math.max(0.15, Math.min(1, 1 - dist / maxDist));
  if (selectedTags.has(bubble.tag)) {
    selectedTags.get(bubble.tag).weight = Math.max(selectedTags.get(bubble.tag).weight, bubble.weight);
  }
}

function handleSearch() {
  const kw = $("searchInput").value.trim();

  if (!kw) return;

  location.href = `results.html?keyword=${encodeURIComponent(kw)}`;
}

function addSelectedTag(tag, weight = 0.7, kind = "mood") {
  const clean = cleanTag(tag);
  if (!clean) return;
  const prev = selectedTags.get(clean);
  selectedTags.set(clean, {
    tag: clean,
    weight: Math.max(prev?.weight || 0, weight),
    kind
  });

  if (groupMode && activeMemberId) {
    const member = groupMembers.find(m => m.id === activeMemberId);
    if (member) {
      const old = member.tags[clean]?.weight || 0;
      member.tags[clean] = { tag: clean, weight: Math.max(old, weight), kind };
      saveGroupMembers();
      renderMembers();
      renderGroupTags();
    }
  }

  bubbles.forEach(b => {
    if (b.tag === clean) b.el.classList.add("selected");
  });

  renderSelectedTags();
}

function removeSelectedTag(tag) {
  selectedTags.delete(tag);
  bubbles.forEach(b => {
    if (b.tag === tag) b.el.classList.remove("selected");
  });
  renderSelectedTags();
  renderRecommendations();
}

function renderSelectedTags() {
  const box = $("selectedTags");
  box.innerHTML = "";

  if (!selectedTags.size) {
    box.innerHTML = `<span class="chip">尚未選擇</span>`;
    return;
  }

  [...selectedTags.values()].forEach(item => {
    const chip = document.createElement("span");
    chip.className = "chip";
    const pct = Math.round(item.weight * 100);
    chip.innerHTML = `${escapeHtml(item.tag)} <small>${pct}%</small> <button aria-label="移除">×</button>`;
    chip.querySelector("button").addEventListener("click", () => removeSelectedTag(item.tag));
    box.appendChild(chip);
  });
}

function cardToMovie(card) {
  if (!card) return null;
  const id = String(card.id || card.movieId || "").trim();
  if (id) {
    const found = allMovies.find(m => String(m.id) === id || String(m.tmdbId || "") === id);
    if (found) return found;
  }
  return {
    id: id || `push-${card.title || "movie"}`,
    title: card.title || "未命名",
    poster: card.poster || card.thumb || "",
    desc: card.desc || card.overview || (Array.isArray(card.matchReasons) ? card.matchReasons.join(" · ") : ""),
    actors: typeof card.actors === "string" ? card.actors : (Array.isArray(card.actors) ? card.actors.join("、") : ""),
    genres: card.genres || [],
    emotions: card.emotions || [],
    atmospheres: card.atmospheres || [],
    moods: card.moods || [],
    year: card.year || "",
    ytId: card.ytId || "",
    url: card.url || "",
  };
}

function renderRecommendMovieItem(list, movie, score = 0, extraMeta = "") {
  const compatibility = getCompatibilityText(score);
  const item = document.createElement("article");
  item.className = "movie-item";
  item.innerHTML = `
    <div class="poster" style="background-image:url('${safeAttr(movie.poster)}')"></div>
    <div class="movie-main-info">
      <h4>${escapeHtml(movie.title)}</h4>
      <div class="movie-meta">
        ${topTags(movie).slice(0, 3).map(t => `<span>${escapeHtml(t)}</span>`).join("")}
        ${extraMeta}
        ${renderFeedbackBadge(movie)}
        ${renderGroupMovieBadge(movie)}
      </div>
      <p class="movie-desc">${escapeHtml(movie.desc || "").slice(0, 72)}${(movie.desc || "").length > 72 ? "..." : ""}</p>
      <p class="movie-actors">演員：${escapeHtml(movie.actors || "暫無演員資料")}</p>
    </div>
    <div class="movie-score">
      <button class="movie-fav-btn ${isFavorite(movie) ? "active" : ""}" type="button" aria-label="收藏電影">
        <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/></svg>
      </button>
      <div class="match-info">
        <strong>${compatibility.value}</strong>
        <small>${compatibility.label}</small>
      </div>
      <small class="view-count">
        <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></svg>
        <span>${getViewCount(movie)} 次</span>
      </small>
      <button class="play-circle" type="button" aria-label="查看電影">
        <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 7 8 5-8 5V7Z"/></svg>
      </button>
    </div>
  `;

  item.querySelector(".movie-fav-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleFavorite(movie);
    updateMemberStats();
    renderRecommendations();
  });

  item.addEventListener("click", () => openModal(movie, score));
  list.appendChild(item);
}

function renderRecommendations(showAll = false) {
  const list = $("recommendList");
  if (!list) return;
  const criteriaActive = hasRecommendationCriteria();
  const needsPopularity = appSettings.prefPop || appSettings.prefNiche;

  // 登入帳號：沒有本機感覺條件時，優先顯示後端個人推薦片單
  if (!criteriaActive && !groupMode && serverRecommendCards.length) {
    const display = showAll ? serverRecommendCards : serverRecommendCards.slice(0, 4);
    list.innerHTML = "";
    display.forEach((card) => {
      const movie = cardToMovie(card);
      if (!movie) return;
      const score = typeof card.score === "number" ? card.score : 0.75;
      const reason = Array.isArray(card.matchReasons) && card.matchReasons.length
        ? `<span class="chip">個人推薦</span>`
        : `<span class="chip">個人推薦</span>`;
      renderRecommendMovieItem(list, movie, score, reason);
    });
    return;
  }

  // maxViews 只在需要熱門/冷門偏好時算一次。
  const maxViews = needsPopularity
    ? Math.max(1, ...allMovies.map(movie => Math.max(0, Number(getViewCount(movie) || 0))))
    : 1;

  let scored = allMovies
    .filter(moviePassesPreferenceFilters)
    .filter(movie => getFeedback(movie) !== "dislike")
    .map(movie => {
      // 切換模式時會清空選擇；沒有任何推薦條件時，完全不需要跑標籤相似度。
      const score = criteriaActive ? computeScore(movie) : 0;
      const popularityRatio = needsPopularity
        ? Math.max(0, Math.min(1, Number(getViewCount(movie) || 0) / maxViews))
        : 0;

      return {
        movie,
        score,
        rankScore: computeRankingScore(movie, score, popularityRatio)
      };
    });

  scored.sort((a, b) => {
    const av = getViewCount(a.movie);
    const bv = getViewCount(b.movie);
    return b.rankScore - a.rankScore || bv - av;
  });

  const filtered = criteriaActive
    ? scored.filter(item => item.score > 0)
    : scored;

  const display = showAll ? filtered : filtered.slice(0, 4);

  if (!display.length) {
    const hint = getCurrentUser()
      ? "目前沒有符合條件的電影。可先為幾部片評分，登入後會自動產生個人推薦。"
      : "目前沒有符合條件的電影。可以減少排除條件、重新選擇感覺，或換個排列。";
    list.innerHTML = `<div class="empty-state">${hint}</div>`;
    return;
  }

  list.innerHTML = "";

  display.forEach(({ movie, score }) => {
    renderRecommendMovieItem(list, movie, score);
  });
}

function hasRecommendationCriteria() {
  const hasPersonal = selectedTags.size > 0;
  const hasGroup = groupMode && getGroupTagMap().size > 0;
  return hasPersonal || hasGroup;
}

function moviePassesPreferenceFilters(movie) {
  const genreText = (movie.genre || []).join(" ").toLowerCase();
  const moodText = (movie.mood || []).join(" ").toLowerCase();
  const allText = [
    movie.title,
    movie.desc,
    genreText,
    moodText,
    ...(movie.keywords || [])
  ].join(" ").toLowerCase();

  if (appSettings.noHorror) {
    const horrorWords = ["恐怖", "驚悚", "鬼", "靈異", "惡魔", "血腥", "horror"];
    if (horrorWords.some(word => allText.includes(word))) return false;
  }

  if (appSettings.noSad) {
    const sadWords = ["悲劇", "悲傷", "心碎", "憂鬱", "沉重", "虐心"];
    if (sadWords.some(word => allText.includes(word))) return false;
  }

  return true;
}

function getPopularityRatio(movie) {
  if (cachedPopularityMaxViews === null) {
    cachedPopularityMaxViews = Math.max(
      1,
      ...allMovies.map(item => Math.max(0, Number(getViewCount(item) || 0)))
    );
  }

  return Math.max(
    0,
    Math.min(1, Number(getViewCount(movie) || 0) / cachedPopularityMaxViews)
  );
}

function normalizeMatchText(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "");
}

function getMovieFeatureGroups(movie) {
  return [
    { values: movie.mood || [], strength: 1.00 },
    { values: movie.genre || [], strength: 0.92 },
    { values: movie.mainScene || [], strength: 0.86 },
    { values: movie.subScene || [], strength: 0.78 },
    { values: movie.keywords || [], strength: 0.74 },
    { values: [movie.title], strength: 0.70 },
    { values: [movie.desc], strength: 0.62 }
  ];
}

function getTagMatchStrength(movie, tag) {
  const needle = normalizeMatchText(tag);
  if (!needle) return 0;

  let best = 0;

  getMovieFeatureGroups(movie).forEach(group => {
    group.values.forEach(value => {
      const haystack = normalizeMatchText(value);
      if (!haystack) return;

      if (haystack === needle) {
        best = Math.max(best, group.strength);
        return;
      }

      if (haystack.includes(needle) || needle.includes(haystack)) {
        best = Math.max(best, group.strength * 0.82);
      }
    });
  });

  return Math.max(0, Math.min(1, best));
}

function computeTagMatchScore(movie, tagItems) {
  if (!tagItems.length) return null;

  let totalPreferenceWeight = 0;
  let matchedPreferenceWeight = 0;
  let matchedCount = 0;

  tagItems.forEach(({ tag, weight }) => {
    const cleanTagValue = String(tag || "").trim();
    if (!cleanTagValue) return;

    const preferenceWeight = Math.max(0.05, Math.min(1, Number(weight) || 0.6));
    const matchStrength = getTagMatchStrength(movie, cleanTagValue);

    totalPreferenceWeight += preferenceWeight;

    if (matchStrength > 0) {
      matchedCount += 1;
      matchedPreferenceWeight += preferenceWeight * matchStrength;
    }
  });

  if (!totalPreferenceWeight) return null;

  const preferenceCoverage = matchedPreferenceWeight / totalPreferenceWeight;

  const movieFeatureCount = Math.max(
    4,
    Math.min(
      10,
      topTags(movie).length || 4
    )
  );

  const movieFeaturePrecision = Math.min(1, matchedCount / movieFeatureCount);
  const evidenceStrength = matchedCount > 0
    ? 1 - Math.exp(-matchedCount / 2)
    : 0;

  const finalScore =
    preferenceCoverage * 0.68 +
    movieFeaturePrecision * 0.20 +
    evidenceStrength * 0.12;

  return Math.max(0, Math.min(1, finalScore));
}

function computeScore(movie) {
  const personalItems = [...selectedTags.values()];
  const personalScore = computeTagMatchScore(movie, personalItems);

  let groupScore = null;
  if (groupMode) {
    const groupItems = [...getGroupTagMap().values()];
    groupScore = computeTagMatchScore(movie, groupItems);
  }

  const available = [];
  if (personalScore !== null) available.push({ score: personalScore, weight: 0.7 });
  if (groupScore !== null) available.push({ score: groupScore, weight: personalScore === null ? 1 : 0.3 });

  if (!available.length) return 0;

  const totalWeight = available.reduce((sum, item) => sum + item.weight, 0);
  const weightedScore = available.reduce((sum, item) => sum + item.score * item.weight, 0) / totalWeight;

  return Math.max(0, Math.min(1, weightedScore));
}

function computeRankingScore(movie, baseScore = null, popularityRatio = null) {
  // 呼叫端如果已經算過 computeScore，就直接重用，不再重算第二次。
  let rankScore = baseScore === null ? computeScore(movie) : baseScore;

  const feedback = feedbacks[getMovieKey(movie)] || {};
  if (typeof feedback.temperature === "number") {
    const feedbackAdjustment = (feedback.temperature - 50) / 500;
    rankScore += feedbackAdjustment;
  } else if (feedback.rating === "like") {
    rankScore += 0.08;
  }

  if (appSettings.prefPop || appSettings.prefNiche) {
    const popularity = popularityRatio === null
      ? getPopularityRatio(movie)
      : popularityRatio;

    if (appSettings.prefPop) rankScore += popularity * 0.12;
    if (appSettings.prefNiche) rankScore += (1 - popularity) * 0.12;
  }

  return rankScore;
}

function getCompatibilityText(score) {
  if (!hasRecommendationCriteria()) {
    return {
      value: "—",
      label: "請先選感覺"
    };
  }

  return {
    value: `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`,
    label: "適合度"
  };
}

function fuzzyTagHit(movie, tag) {
  const all = topTags(movie);
  return all.some(t => t.includes(tag) || tag.includes(t));
}

function topTags(movie) {
  const values = [
    ...(movie.genre || []),
    ...(movie.mood || []),
    ...(movie.mainScene || []),
    ...(movie.subScene || []),
    ...(movie.keywords || [])
  ];
  const seen = new Set();
  return values.filter(tag => {
    const clean = cleanTag(tag);
    const key = clean.toLowerCase();
    if (!clean || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function openModal(movie, score = 0) {
  currentModalMovie = movie;
  incrementView(movie);
  saveHistory(movie, score);
  updateMemberStats();
  $("modalTitle").textContent = movie.title;
  $("modalDesc").textContent = movie.desc;

const oldActors = document.getElementById("modalActors");
if (oldActors) oldActors.remove();

const actorsBox = document.createElement("p");
actorsBox.id = "modalActors";
actorsBox.className = "modal-actors";
actorsBox.textContent = `演員：${movie.actors || "暫無演員資料"}`;

$("modalDesc").insertAdjacentElement("afterend", actorsBox);
  $("modalCover").style.backgroundImage = `url('${movie.poster}')`;

  const meta = [
    movie.year,
    movie.duration,
    ...topTags(movie).slice(0, 12),
    hasRecommendationCriteria() ? `${Math.round(Math.max(0, Math.min(1, score)) * 100)}% 適合` : "尚未計算適合度"
  ].filter(Boolean);

  $("modalMeta").innerHTML = meta.map(m => `<span>${escapeHtml(m)}</span>`).join("");
  $("modalViewCount").innerHTML = `<span class="icon-label"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></svg><span>${getViewCount(movie)} 次瀏覽</span></span>`;
  updateFeedbackUI(movie);
  updateGroupVoteUI(movie);
  updateFavoriteUI(movie);

  const trailer = $("trailerLink");
  if (movie.trailer) {
    trailer.href = movie.trailer;
    trailer.style.display = "inline-flex";
  } else {
    trailer.removeAttribute("href");
    trailer.style.display = "none";
  }

  $("movieModal").classList.add("active");
  $("movieModal").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  renderRecommendations();
}

function closeModal() {
  $("movieModal").classList.remove("active");
  $("movieModal").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}



function setActiveNav(id) {
  document.querySelectorAll(".side-nav button").forEach(btn => {
    const target = btn.getAttribute("data-target") || "";
    btn.classList.toggle("active", btn.id === id || target === id);
  });
}

function storageOwnerId() {
  const user = getCurrentUser();
  return user?.username || null;
}

function storageKey(type) {
  const owner = storageOwnerId();
  if (!owner) return null;

  const prefix = type === "history" ? HISTORY_PREFIX : FAVORITE_PREFIX;
  return `${prefix}-${owner}`;
}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback));
  } catch {
    return fallback;
  }
}

function saveJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function loadUsers() {
  const users = loadJson(AUTH_USERS_KEY, []);
  return Array.isArray(users) ? users : [];
}

function saveUsers(users) {
  saveJson(AUTH_USERS_KEY, users);
}

async function apiAuth(path, body) {
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem(AUTH_TOKEN_KEY) || "";
  if (token) headers.Authorization = `Bearer ${token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    const res = await fetch(`${FILMDB_BASE}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body || {}),
      signal: controller.signal,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `請求失敗（${res.status}）`);
    }
    return data;
  } catch (e) {
    if (e?.name === "AbortError") {
      throw new Error("伺服器喚醒逾時，請再試一次（首次連線可能較慢）");
    }
    if (e instanceof TypeError) {
      throw new Error("無法連線伺服器，請檢查網路後再試");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function authHeaders() {
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem(AUTH_TOKEN_KEY) || "";
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function apiRecommendMe({ publish = true, force = false, limit = 20 } = {}) {
  const user = getCurrentUser();
  const token = localStorage.getItem(AUTH_TOKEN_KEY) || "";
  if (!user?.username || !token) return null;
  let feedbacksPayload = {};
  try {
    feedbacksPayload = JSON.parse(localStorage.getItem("feelmovie-feedbacks") || "{}");
  } catch (_) {
    feedbacksPayload = {};
  }
  const res = await fetchWithTimeout(`${FILMDB_BASE}/api/recommend/me`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      userName: user.username,
      publish: !!publish,
      forcePublish: !!force,
      limit,
      feedbacks: feedbacksPayload,
    }),
  }, 25000);
  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }
  if (!res.ok || !data.ok) {
    throw new Error(data.error || `個人推薦失敗（${res.status}）`);
  }
  return data;
}

async function refreshPersonalRecommend({ publish = true, force = false } = {}) {
  try {
    const data = await apiRecommendMe({ publish, force, limit: 20 });
    if (!data) return false;
    const cards = Array.isArray(data.cards) && data.cards.length
      ? data.cards
      : (data.pushFeed?.cards || []);
    serverRecommendCards = Array.isArray(cards) ? cards : [];
    renderRecommendations();
    return true;
  } catch (e) {
    console.warn("personal recommend failed", e);
    return false;
  }
}

async function apiRoomRecommend({ publish = false, limit = 12 } = {}) {
  const roomCode = backendRoomCode(getCurrentRoomCode());
  if (!roomCode) throw new Error("尚未設定房間代碼");
  const members = (groupMembers || []).map((m) => ({
    name: m.name,
    tags: m.tags || {},
  }));
  const res = await fetchWithTimeout(`${FILMDB_BASE}/api/room/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      roomCode,
      limit,
      publish: !!publish,
      message: "房間成員個人推薦",
      members,
    }),
  }, 30000);
  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }
  if (!res.ok || !data.ok) {
    throw new Error(data.error || `房間推薦失敗（${res.status}）`);
  }
  return data;
}

async function refreshRoomMemberRecommends({ publish = true } = {}) {
  const btn = $("roomMemberRecommendBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "產生中…";
  }
  try {
    const data = await apiRoomRecommend({ publish, limit: 8 });
    const map = {};
    for (const row of data.results || []) {
      if (!row?.userName) continue;
      map[row.userName] = row;
    }
    memberRecommendByName = map;
    memberRecommendMeta = {
      published: data.published,
      total: data.total,
      roomCode: data.roomCode,
      lastPushAt: data.lastPushAt,
    };
    renderMemberRecommendPanel();
    return data;
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "為每位成員產生個人片單";
    }
  }
}

function renderMemberRecommendPanel() {
  const box = $("memberRecommendPanel");
  if (!box) return;
  const names = Object.keys(memberRecommendByName || {});
  if (!names.length) {
    box.classList.remove("has-results");
    box.innerHTML = `<div class="empty-state">每位成員選好感覺後，點上方按鈕即可產生各自的推薦片單。</div>`;
    return;
  }
  box.classList.add("has-results");
  const meta = memberRecommendMeta || {};
  const head = meta.published != null
    ? `<p class="member-rec-meta">已為 ${meta.published || 0}/${meta.total || names.length} 位成員產生片單${meta.lastPushAt ? ` · ${escapeHtml(String(meta.lastPushAt))}` : ""}</p>`
    : "";
  box.innerHTML = head + names.map((name) => {
    const row = memberRecommendByName[name] || {};
    const cards = Array.isArray(row.cards) ? row.cards.slice(0, 4) : [];
    const sourceLabel = row.source === "tags" ? "依標籤" : row.source === "prefs" ? "依喜好" : "";
    const status = row.ok
      ? `${cards.length} 部${sourceLabel ? ` · ${sourceLabel}` : ""}`
      : (row.error || "略過");
    const cardsHtml = cards.length
      ? `<div class="recommend-list member-rec-list">${cards.map((card) => {
          const movie = cardToMovie(card) || {};
          return `<article class="movie-item member-rec-item" data-id="${safeAttr(movie.id || "")}">
            <div class="poster" style="background-image:url('${safeAttr(movie.poster || "")}')"></div>
            <div class="movie-main-info">
              <h4>${escapeHtml(movie.title || "")}</h4>
            </div>
          </article>`;
        }).join("")}</div>`
      : `<div class="empty-state">${escapeHtml(status)}</div>`;
    return `<section class="member-rec-block">
      <div class="recommend-head">
        <div>
          <h3>${escapeHtml(name)}</h3>
          <p>${escapeHtml(status)}</p>
        </div>
      </div>
      ${cardsHtml}
    </section>`;
  }).join("");

  box.querySelectorAll(".member-rec-item").forEach((el) => {
    el.addEventListener("click", () => {
      const id = el.getAttribute("data-id");
      const movie = allMovies.find(m => String(m.id) === String(id));
      if (movie) openModal(movie, 0.7);
    });
  });
}

function mergeListById(primary = [], secondary = [], limit = 0) {
  const map = new Map();
  for (const item of [...(Array.isArray(primary) ? primary : []), ...(Array.isArray(secondary) ? secondary : [])]) {
    if (!item || item.id == null) continue;
    const key = String(item.id);
    if (!map.has(key)) map.set(key, item);
  }
  const out = [...map.values()];
  return limit > 0 ? out.slice(0, limit) : out;
}

function buildLocalUserState() {
  return {
    favorites: loadCollection("favorites"),
    history: loadCollection("history"),
    settings: loadJson("moodluma_settings", {}),
    feedbacks: (() => {
      try {
        return JSON.parse(localStorage.getItem("feelmovie-feedbacks") || "{}");
      } catch {
        return {};
      }
    })(),
    viewCounts: (() => {
      try {
        return JSON.parse(localStorage.getItem("feelmovie-view-counts") || "{}");
      } catch {
        return {};
      }
    })(),
    bubbleMode: localStorage.getItem(BUBBLE_MODE_KEY) === "exhibition" ? "exhibition" : "normal",
  };
}

function applyUserStateLocally(data) {
  if (!data || typeof data !== "object") return;
  if (Array.isArray(data.favorites)) saveJson(storageKey("favorites"), data.favorites);
  if (Array.isArray(data.history)) saveJson(storageKey("history"), data.history);
  if (data.settings && typeof data.settings === "object") {
    appSettings = { ...appSettings, ...data.settings };
    saveJson("moodluma_settings", appSettings);
  }
  if (data.feedbacks && typeof data.feedbacks === "object") {
    localStorage.setItem("feelmovie-feedbacks", JSON.stringify(data.feedbacks));
  }
  if (data.viewCounts && typeof data.viewCounts === "object") {
    localStorage.setItem("feelmovie-view-counts", JSON.stringify(data.viewCounts));
  }
  if (data.bubbleMode === "exhibition" || data.bubbleMode === "normal") {
    bubbleMode = data.bubbleMode;
    localStorage.setItem(BUBBLE_MODE_KEY, bubbleMode);
  }
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function apiSyncPull() {
  const user = getCurrentUser();
  const token = localStorage.getItem(AUTH_TOKEN_KEY) || "";
  if (!user?.username || !token) return null;
  const qs = new URLSearchParams({ scope: "user", owner: user.username });
  const res = await fetchWithTimeout(`${FILMDB_BASE}/api/sync?${qs}`, {
    method: "GET",
    headers: authHeaders(),
  }, 20000);
  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }
  if (!res.ok || !data.ok) {
    throw new Error(data.error || `同步讀取失敗（${res.status}）`);
  }
  return data.data || {};
}

async function apiSyncPush(state) {
  const user = getCurrentUser();
  const token = localStorage.getItem(AUTH_TOKEN_KEY) || "";
  if (!user?.username || !token) return null;
  const res = await fetchWithTimeout(`${FILMDB_BASE}/api/sync`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({
      scope: "user",
      owner: user.username,
      merge: true,
      updatedAt: new Date().toISOString(),
      data: state || buildLocalUserState(),
    }),
  }, 20000);
  let data = {};
  try {
    data = await res.json();
  } catch (_) {
    data = {};
  }
  if (!res.ok || !data.ok) {
    throw new Error(data.error || `同步寫入失敗（${res.status}）`);
  }
  return data;
}

async function syncUserStateFromCloud({ pushAfter = true } = {}) {
  const user = getCurrentUser();
  if (!user?.username || !localStorage.getItem(AUTH_TOKEN_KEY)) return false;
  try {
    const remote = (await apiSyncPull()) || {};
    const local = buildLocalUserState();
    const merged = {
      favorites: mergeListById(local.favorites, remote.favorites || []),
      history: mergeListById(local.history, remote.history || [], 30),
      settings: { ...(remote.settings || {}), ...(local.settings || {}) },
      feedbacks: { ...(remote.feedbacks || {}), ...(local.feedbacks || {}) },
      viewCounts: { ...(remote.viewCounts || {}), ...(local.viewCounts || {}) },
      bubbleMode: local.bubbleMode || remote.bubbleMode || "normal",
    };
    applyUserStateLocally(merged);
    if (pushAfter) {
      await apiSyncPush(merged);
    }
    renderCollection();
    syncCollectionButtonsUI();
    updateMemberStats();
    return true;
  } catch (e) {
    console.warn("user sync failed", e);
    return false;
  }
}

let userSyncPushTimer = null;
function scheduleUserStatePush() {
  if (!getCurrentUser() || !localStorage.getItem(AUTH_TOKEN_KEY)) return;
  clearTimeout(userSyncPushTimer);
  userSyncPushTimer = setTimeout(() => {
    apiSyncPush(buildLocalUserState()).catch((e) => console.warn("user sync push failed", e));
  }, 600);
}

function getCurrentUser() {
  try {
    const user = JSON.parse(localStorage.getItem(CURRENT_USER_KEY) || "null");
    return user && user.username ? user : null;
  } catch {
    return null;
  }
}

function setCurrentUser(user, token) {
  localStorage.setItem(CURRENT_USER_KEY, JSON.stringify({
    username: user.username,
    email: user.email || "",
    createdAt: user.createdAt || new Date().toISOString()
  }));
  if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function openAuth(mode = "login") {
  setAuthMode(mode);
  $("authModal")?.classList.add("active");
  $("authModal")?.setAttribute("aria-hidden", "false");
  $("authMessage").textContent = "";
  $("authPassword").value = "";
  setTimeout(() => $("authUsername")?.focus(), 50);
}

function closeAuth() {
  $("authModal")?.classList.remove("active");
  $("authModal")?.setAttribute("aria-hidden", "true");
}

function setAuthMode(mode) {
  authMode = mode === "register" ? "register" : "login";
  $("authTitle").textContent = authMode === "register" ? "會員註冊" : "會員登入";
  $("authSubmit").textContent = authMode === "register" ? "建立帳號" : "登入";
  $("authEmailWrap").style.display = authMode === "register" ? "grid" : "none";
  $("authLoginTab").classList.toggle("active", authMode === "login");
  $("authRegisterTab").classList.toggle("active", authMode === "register");
  $("authMessage").textContent = "";
}

async function handleAuthSubmit() {
  const username = $("authUsername").value.trim();
  const email = $("authEmail").value.trim();
  const password = $("authPassword").value;
  const msg = $("authMessage");
  const submitBtn = $("authSubmit");
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (!username || !password) {
    msg.textContent = "請輸入帳號與密碼。";
    msg.className = "auth-message error";
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = authMode === "register" ? "註冊中…" : "登入中…";
  }

  try {
    if (authMode === "register") {
      if (!emailPattern.test(email)) {
        throw new Error("請輸入正確的 Email 格式，例如：name@example.com");
      }
      const data = await apiAuth("/api/auth/register", { username, email, password });
      setCurrentUser(data.user, data.token);
      msg.textContent = "註冊成功，正在同步雲端資料…";
      msg.className = "auth-message success";
      updateAuthUI();
      const synced = await syncUserStateFromCloud();
      await refreshPersonalRecommend({ publish: true });
      updateMemberStats();
      msg.textContent = synced
        ? "註冊成功，已自動登入（已同步至雲端）。"
        : "註冊成功，已登入（雲端同步稍後再試）。";
      setTimeout(closeAuth, 450);
      return;
    }

    const data = await apiAuth("/api/auth/login", { username, password });
    setCurrentUser(data.user, data.token);
    msg.textContent = "登入成功，正在同步雲端資料…";
    msg.className = "auth-message success";
    updateAuthUI();
    if (Array.isArray(data.recommend?.cards) && data.recommend.cards.length) {
      serverRecommendCards = data.recommend.cards;
      renderRecommendations();
    }
    const synced = await syncUserStateFromCloud();
    await refreshPersonalRecommend({ publish: true });
    updateMemberStats();
    const recN = serverRecommendCards.length;
    msg.textContent = synced
      ? (recN ? `登入成功（已同步，並推送 ${recN} 部個人推薦）。` : "登入成功（已同步收藏／歷史）。")
      : "登入成功（雲端同步稍後再試）。";
    setTimeout(closeAuth, 350);
  } catch (e) {
    msg.textContent = e.message || "操作失敗，請稍後再試。";
    msg.className = "auth-message error";
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = authMode === "register" ? "建立帳號" : "登入";
    }
  }
}

function openForgotPassword() {
  closeAuth();
  ["resetUsername", "resetEmail", "resetNewPassword", "resetConfirmPassword"].forEach(id => {
    if ($(id)) $(id).value = "";
  });
  const msg = $("resetPasswordMessage");
  if (msg) {
    msg.textContent = "";
    msg.className = "auth-message";
  }
  $("forgotPasswordModal")?.classList.add("active");
  $("forgotPasswordModal")?.setAttribute("aria-hidden", "false");
  setTimeout(() => $("resetUsername")?.focus(), 50);
}

function closeForgotPassword() {
  $("forgotPasswordModal")?.classList.remove("active");
  $("forgotPasswordModal")?.setAttribute("aria-hidden", "true");
}

async function handlePasswordReset() {
  const username = $("resetUsername")?.value.trim() || "";
  const email = $("resetEmail")?.value.trim() || "";
  const newPassword = $("resetNewPassword")?.value || "";
  const confirmPassword = $("resetConfirmPassword")?.value || "";
  const msg = $("resetPasswordMessage");
  const fail = (text) => {
    msg.textContent = text;
    msg.className = "auth-message error";
  };

  if (!username || !email || !newPassword || !confirmPassword) {
    fail("請完整填寫所有必填欄位。");
    return;
  }
  if (newPassword.length < 6) {
    fail("新密碼至少需要 6 個字元。");
    return;
  }
  if (newPassword !== confirmPassword) {
    fail("兩次輸入的新密碼不一致。");
    return;
  }

  try {
    await apiAuth("/api/auth/reset", {
      username,
      email,
      newPassword,
    });
    msg.textContent = "密碼重設成功，請使用新密碼登入。";
    msg.className = "auth-message success";
    setTimeout(() => {
      closeForgotPassword();
      openAuth("login");
      $("authUsername").value = username;
    }, 700);
  } catch (e) {
    fail(e.message || "重設失敗，請稍後再試。");
  }
}

function logoutUser() {
  localStorage.removeItem(CURRENT_USER_KEY);
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(`${HISTORY_PREFIX}-${GUEST_ID}`);
  localStorage.removeItem(`${FAVORITE_PREFIX}-${GUEST_ID}`);

  closeAuth();
  closeLibrary();
  closeCollectionChoice();
  document.querySelector('[data-target="page-home"]')?.click();

  updateAuthUI();
  updateMemberStats();
  renderRecommendations();
  renderExploreResults($("exploreSearchInput")?.value || "");
  renderCollection();
  syncCollectionButtonsUI();

  if (currentModalMovie) {
    updateFavoriteUI(currentModalMovie);
  }

  openMemberSpace();
}

function updateAuthUI() {
  const user = getCurrentUser();
  const loginBtn = $("loginBtn");
  const registerBtn = $("registerBtn");
  const memberBtn = $("memberSpaceBtn");

  if (!loginBtn || !registerBtn || !memberBtn) return;

  loginBtn.style.display = user ? "none" : "inline-flex";
  registerBtn.style.display = user ? "none" : "inline-flex";
  memberBtn.textContent = user ? user.username : "會員空間";
}

function openMemberSpace() {
  const user = getCurrentUser();
  const welcome = $("memberWelcome");
  if (welcome) {
    welcome.textContent = user
      ? `目前登入帳號：${user.username}${user.email ? `（${user.email}）` : ""}`
      : "目前尚未登入。登入後即可查看你的收藏與歷史紀錄。";
  }

  $("memberLoginFromSpace").style.display = user ? "none" : "inline-flex";
  $("logoutBtn").style.display = user ? "inline-flex" : "none";
  updateMemberStats();
  $("memberModal")?.classList.add("active");
  $("memberModal")?.setAttribute("aria-hidden", "false");
}

function closeMemberSpace() {
  $("memberModal")?.classList.remove("active");
  $("memberModal")?.setAttribute("aria-hidden", "true");
}

function updateMemberStats() {
  const history = loadCollection("history");
  const favorites = loadCollection("favorites");
  if ($("memberHistoryCount")) $("memberHistoryCount").textContent = history.length;
  if ($("memberFavoriteCount")) $("memberFavoriteCount").textContent = favorites.length;
}

function movieSnapshot(movie, score = 0) {
  return {
    id: movie.id,
    title: movie.title,
    desc: movie.desc,
    poster: movie.poster,
    trailer: movie.trailer,
    year: movie.year || "",
    duration: movie.duration || "",
    actors: movie.actors || "",
    genre: Array.isArray(movie.genre) ? movie.genre : toArray(movie.genre),
    mood: Array.isArray(movie.mood) ? movie.mood : toArray(movie.mood),
    mainScene: Array.isArray(movie.mainScene) ? movie.mainScene : toArray(movie.mainScene),
    subScene: Array.isArray(movie.subScene) ? movie.subScene : toArray(movie.subScene),
    score,
    savedAt: new Date().toISOString(),
    collectionType: movie.collectionType || "想看",
    addDate: movie.addDate || new Date().toLocaleDateString("zh-TW", { year: "numeric", month: "2-digit", day: "2-digit" })
  };
}

function hydrateMovie(item) {
  const found = allMovies.find(movie => String(movie.id) === String(item.id) || movie.title === item.title);
  if (found) return found;
  return {
    ...item,
    genre: Array.isArray(item.genre) ? item.genre : toArray(item.genre),
    mood: Array.isArray(item.mood) ? item.mood : toArray(item.mood),
    mainScene: Array.isArray(item.mainScene) ? item.mainScene : toArray(item.mainScene),
    subScene: Array.isArray(item.subScene) ? item.subScene : toArray(item.subScene),
    views: item.views || 0,
    raw: item.raw || {}
  };
}

function loadCollection(type) {
  const key = storageKey(type);
  if (!key) return [];

  const items = loadJson(key, []);
  return Array.isArray(items) ? items : [];
}

function saveCollection(type, items) {
  const key = storageKey(type);
  if (!key) return;

  saveJson(key, items);
  // 收藏／歷史一變就立刻推雲端（另保留 debounce 合併連點）
  scheduleUserStatePush();
  apiSyncPush(buildLocalUserState()).catch((e) => console.warn("user sync push failed", e));
}

function saveHistory(movie, score = 0) {
  if (!getCurrentUser()) return;

  const items = loadCollection("history");
  const snapshot = movieSnapshot(movie, score);
  const next = [snapshot, ...items.filter(item => String(item.id) !== String(movie.id))].slice(0, 30);
  saveCollection("history", next);
}

function isFavorite(movie) {
  return loadCollection("favorites").some(item => String(item.id) === String(movie.id));
}

function toggleFavorite(movie, collectionType = null) {
  if (!getCurrentUser()) {
    openAuth("login");
    return;
  }

  const items = loadCollection("favorites");
  const exists = items.some(item => String(item.id) === String(movie.id));

  const next = exists
    ? items.filter(item => String(item.id) !== String(movie.id))
    : [movieSnapshot({ ...movie, collectionType: collectionType || movie.collectionType || "想看" }), ...items];

  saveCollection("favorites", next);
  renderCollection();
  syncCollectionButtonsUI();
}

function updateFavoriteUI(movie) {
  const btn = $("favoriteBtn");
  if (!btn || !movie) return;
  const active = isFavorite(movie);
  btn.classList.toggle("active", active);
  btn.textContent = active ? "♥ 已收藏" : "♡ 加入收藏";
}

function openLibrary(type = "favorites") {
  libraryMode = type === "history" ? "history" : "favorites";
  renderLibrary();
  $("libraryModal")?.classList.add("active");
  $("libraryModal")?.setAttribute("aria-hidden", "false");
}

function closeLibrary() {
  $("libraryModal")?.classList.remove("active");
  $("libraryModal")?.setAttribute("aria-hidden", "true");
}

function renderLibrary() {
  const title = $("libraryTitle");
  const label = $("libraryLabel");
  const desc = $("libraryDesc");
  const clearBtn = $("libraryClearBtn");
  const list = $("libraryList");
  if (!list) return;

  const isHistory = libraryMode === "history";
  const items = loadCollection(libraryMode);
  if (title) title.textContent = isHistory ? "歷史紀錄" : "收藏電影";
  if (label) label.textContent = isHistory ? "History" : "Favorites";
  if (desc) desc.textContent = isHistory ? "點擊歷史紀錄可以重新開啟電影詳細資料。" : "點擊收藏電影可以重新開啟電影詳細資料。";
  if (clearBtn) clearBtn.textContent = isHistory ? "清空歷史" : "清空收藏";

  if (!items.length) {
    list.innerHTML = `<div class="empty-state">目前沒有${isHistory ? "歷史紀錄" : "收藏電影"}。</div>`;
    return;
  }

  list.innerHTML = "";
  items.forEach(item => {
    const movie = hydrateMovie(item);
    const card = document.createElement("article");
    card.className = "library-card";
    const tags = topTags(movie).slice(0, 3).map(t => `<span>${escapeHtml(t)}</span>`).join("");
    const timeText = item.savedAt ? new Date(item.savedAt).toLocaleString("zh-TW") : "";
    card.innerHTML = `
      <div class="library-poster" style="background-image:url('${safeAttr(movie.poster)}')"></div>
      <div class="library-info">
        <h3>${escapeHtml(movie.title)}</h3>
        <p>${escapeHtml(movie.desc || "目前沒有簡介").slice(0, 86)}${movie.desc && movie.desc.length > 86 ? "..." : ""}</p>
        <div class="movie-meta">${tags}</div>
        <small>${timeText}</small>
      </div>
      ${!isHistory ? `<button class="library-remove" type="button">移除</button>` : ""}
    `;
    card.addEventListener("click", () => {
      closeLibrary();
      openModal(movie, item.score || 0.1);
    });
    card.querySelector(".library-remove")?.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFavorite(movie);
      renderLibrary();
      updateMemberStats();
      renderRecommendations();
    });
    list.appendChild(card);
  });
}

function clearCurrentLibrary() {
  if (!confirm(`確定要清空${libraryMode === "history" ? "歷史紀錄" : "收藏電影"}嗎？`)) return;
  saveCollection(libraryMode, []);
  renderLibrary();
  updateMemberStats();
  renderRecommendations();
}


function bindPageNavigation() {
  const navBtns = document.querySelectorAll(".nav-btn");
  const pageViews = document.querySelectorAll(".page-view");
  navBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-target");
      if (!targetId) return;
      navBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      pageViews.forEach(page => page.classList.toggle("active", page.id === targetId));
      if (targetId === "page-explore") renderExploreResults($("exploreSearchInput")?.value.trim() || "");
      if (targetId === "page-collection") renderCollection();
      if (targetId === "page-party") {
        renderMembers();
        renderGroupTags();
      }
    });
  });
}

function bindExploreUI() {
  const exSearchInput = $("exploreSearchInput");
  const exSearchBtn = $("exploreSearchBtn");
  if (exSearchBtn && exSearchInput) {
    exSearchBtn.addEventListener("click", () => renderExploreResults(exSearchInput.value.trim()));
    exSearchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") renderExploreResults(exSearchInput.value.trim());
    });
  }

  document.querySelectorAll(".cat-btn, .tag-pills button").forEach(btn => {
    btn.addEventListener("click", () => {
      const rawText = btn.textContent || "";
      const cleanedText = rawText.replace(/[^a-zA-Z\u4e00-\u9fa5]/g, "").trim();
      const intentMap = {
        "想放鬆一下": "放鬆",
        "想哭一場": "感人",
        "想看刺激的": "動作",
        "適合下雨天": "雨夜",
        "適合睡前看": "安靜",
        "適合跟朋友一起看": "歡樂"
      };
      const finalKeyword = intentMap[cleanedText] || cleanedText;
      if (exSearchInput) exSearchInput.value = finalKeyword;
      renderExploreResults(finalKeyword);
    });
  });
}

function computeExploreMatchScore(movie, aliases = []) {
  const needles = aliases
    .map(alias => String(alias || "").trim().toLowerCase())
    .filter(Boolean);

  if (!needles.length) return null;

  const fields = [
    { values: [movie.title], score: 100 },
    { values: movie.genre || [], score: 96 },
    { values: movie.mood || [], score: 92 },
    { values: movie.keywords || [], score: 90 },
    { values: [...(movie.mainScene || []), ...(movie.subScene || [])], score: 86 },
    { values: [movie.desc], score: 74 },
    { values: [movie.actors], score: 68 }
  ];

  let best = 0;

  fields.forEach(field => {
    const haystack = field.values.join(" ").toLowerCase();
    if (!haystack) return;

    needles.forEach(needle => {
      if (!needle) return;
      if (haystack.includes(needle)) {
        best = Math.max(best, field.score);
      }
    });
  });

  return best || 60;
}

function renderExploreResults(keyword = "") {
  const list = $("exploreResultList");
  if (!list) return;

  let targetMovies = [...allMovies];
  const key = String(keyword || "").trim().toLowerCase();
  if (key) {
    const aliases = CATEGORY_RULES[key] || [key];
    targetMovies = targetMovies.filter(movie => {
      const movieText = [
        movie.title,
        movie.desc,
        movie.actors,
        ...(movie.genre || []),
        ...(movie.mood || []),
        ...(movie.mainScene || []),
        ...(movie.subScene || []),
        ...(movie.keywords || [])
      ].join(" ").toLowerCase();
      return aliases.some(alias => movieText.includes(String(alias).toLowerCase()));
    });
  }

  if (appSettings.noHorror) {
    targetMovies = targetMovies.filter(m => !m.genre.includes("恐怖") && !m.genre.includes("驚悚"));
  }
  if (appSettings.noSad) {
    targetMovies = targetMovies.filter(m => !m.genre.includes("悲劇") && !m.mood.includes("悲傷") && !m.mood.includes("心碎"));
  }
  if (appSettings.prefPop) {
    targetMovies.sort((a, b) => getViewCount(b) - getViewCount(a));
  } else if (appSettings.prefNiche) {
    targetMovies.sort((a, b) => getViewCount(a) - getViewCount(b));
  } else {
    targetMovies.sort(() => Math.random() - 0.5);
  }

  const displayMovies = targetMovies.slice(0, 18);
  if (!displayMovies.length) {
    list.innerHTML = `<div class="empty-state">找不到相關電影，試試其他分類吧！</div>`;
    return;
  }

  list.className = "explore-result-grid";
  list.innerHTML = "";
  displayMovies.forEach(movie => {
    const card = document.createElement("article");
    card.className = "explore-movie-card";
    const tags = topTags(movie).slice(0, 5).map(t => `<span>${escapeHtml(t)}</span>`).join("");
    const aliases = key ? (CATEGORY_RULES[key] || [key]) : [];
    const exploreScore = computeExploreMatchScore(movie, aliases);
    const collected = isFavorite(movie);
    const scoreBadge = exploreScore === null ? "探索" : `${exploreScore}% 匹配`;
    card.innerHTML = `
      <div class="explore-poster" style="background-image:url('${safeAttr(movie.poster)}')">
        <div class="explore-score-badge">${scoreBadge}</div>
      </div>
      <div class="explore-info">
        <h4>${escapeHtml(movie.title)}</h4>
        <div class="explore-meta">
          <div class="explore-tags">${tags}</div>
          <button class="add-col-card-btn ${collected ? "collected" : ""}" data-id="${safeAttr(movie.id)}" type="button" aria-label="收藏">${collected ? "✓ 已收藏" : "＋ 加入收藏"}</button>
        </div>
      </div>
    `;
    card.addEventListener("click", (e) => {
      if (e.target.closest(".add-col-card-btn")) {
        e.stopPropagation();
        if (!getCurrentUser()) {
          openAuth("login");
          return;
        }
        if (isFavorite(movie)) {
          toggleFavorite(movie);
          updateMemberStats();
          renderExploreResults($("exploreSearchInput")?.value || "");
          renderRecommendations();
        } else {
          pendingMovie = movie;
          openCollectionChoice();
        }
        return;
      }
      openModal(movie, exploreScore === null ? 0 : exploreScore / 100);
    });
    list.appendChild(card);
  });
}

function bindCollectionUI() {
  $("colClose")?.addEventListener("click", closeCollectionChoice);
  $("colBackdrop")?.addEventListener("click", closeCollectionChoice);

  document.querySelectorAll(".col-opt-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!pendingMovie) return;
      const type = btn.getAttribute("data-type") || "想看";
      toggleFavorite(pendingMovie, type);
      pendingMovie = null;
      closeCollectionChoice();
      renderCollection();
      renderExploreResults($("exploreSearchInput")?.value || "");
      renderRecommendations();
      updateMemberStats();
    });
  });

  document.querySelectorAll(".collection-tabs .tab-btn").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".collection-tabs .tab-btn").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentTab = tab.textContent.trim();
      renderCollection();
    });
  });

  $("goExploreBtn")?.addEventListener("click", () => {
    document.querySelector('[data-target="page-explore"]')?.click();
  });
}

function openCollectionChoice() {
  $("collectionModal")?.classList.add("active");
  $("collectionModal")?.setAttribute("aria-hidden", "false");
}

function closeCollectionChoice() {
  $("collectionModal")?.classList.remove("active");
  $("collectionModal")?.setAttribute("aria-hidden", "true");
}

function renderCollection() {
  const list = $("collectionList");
  const emptyState = $("collectionEmpty");
  if (!list || !emptyState) return;
  const favorites = loadCollection("favorites");
  const filteredCollections = currentTab === "全部收藏"
    ? favorites
    : favorites.filter(m => (m.collectionType || "想看") === currentTab);

  if (!filteredCollections.length) {
    list.style.display = "none";
    emptyState.style.display = "flex";
    return;
  }

  list.style.display = "grid";
  emptyState.style.display = "none";
  list.innerHTML = "";

  filteredCollections.forEach(item => {
    const movie = hydrateMovie(item);
    const card = document.createElement("article");
    card.className = "explore-movie-card";
    const tags = topTags(movie).slice(0, 5).map(t => `<span>${escapeHtml(t)}</span>`).join("");
    const type = item.collectionType || "想看";
    const date = item.addDate || (item.savedAt ? new Date(item.savedAt).toLocaleDateString("zh-TW") : "近期");
    card.innerHTML = `
      <div class="explore-poster" style="background-image:url('${safeAttr(movie.poster)}')"></div>
      <div class="explore-info">
        <div class="col-badge">${escapeHtml(type)}</div>
        <h4>${escapeHtml(movie.title)}</h4>
        <div class="explore-tags" style="margin-bottom: 12px;">${tags}</div>
        <div class="collection-footer">
          <span>收藏於 ${escapeHtml(date)}</span>
          <button class="delete-btn" type="button" title="移除收藏">🗑️</button>
        </div>
      </div>
    `;
    card.addEventListener("click", (e) => {
      if (e.target.closest(".delete-btn")) {
        e.stopPropagation();
        toggleFavorite(movie);
        renderCollection();
        renderExploreResults($("exploreSearchInput")?.value || "");
        renderRecommendations();
        updateMemberStats();
        return;
      }
      openModal(movie, item.score || 0.95);
    });
    list.appendChild(card);
  });
}

function syncCollectionButtonsUI() {
  document.querySelectorAll(".add-col-card-btn").forEach(btn => {
    const movieId = btn.getAttribute("data-id");
    if (!movieId) return;
    const collected = loadCollection("favorites").some(m => String(m.id) === String(movieId));
    btn.textContent = collected ? "✓ 已收藏" : "＋ 加入收藏";
    btn.classList.toggle("collected", collected);
  });
}

function bindSettingsUI() {
  const applyVisualSettings = () => {
    if ($("setThemeDark")) $("setThemeDark").checked = appSettings.themeDark;
    if ($("setAnim")) $("setAnim").checked = appSettings.anim;
    if ($("setPrefPop")) $("setPrefPop").checked = appSettings.prefPop;
    if ($("setPrefNiche")) $("setPrefNiche").checked = appSettings.prefNiche;
    if ($("setNoHorror")) $("setNoHorror").checked = appSettings.noHorror;
    if ($("setNoSad")) $("setNoSad").checked = appSettings.noSad;

    document.querySelectorAll(".seg-btn").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-val") === appSettings.cardSize);
    });

    document.body.classList.toggle("light-mode", !appSettings.themeDark);
    document.documentElement.style.colorScheme = appSettings.themeDark ? "dark" : "light";

    document.body.classList.toggle("disable-animations", !appSettings.anim);

    document.body.classList.remove("card-size-small", "card-size-large");
    if (appSettings.cardSize === "小") document.body.classList.add("card-size-small");
    if (appSettings.cardSize === "大") document.body.classList.add("card-size-large");
  };

  const refreshBySettings = () => {
    applyVisualSettings();
    renderExploreResults($("exploreSearchInput")?.value || "");
    renderRecommendations();
  };

  applyVisualSettings();

  const toggleMap = {
    setThemeDark: "themeDark",
    setAnim: "anim",
    setPrefPop: "prefPop",
    setPrefNiche: "prefNiche",
    setNoHorror: "noHorror",
    setNoSad: "noSad"
  };

  Object.keys(toggleMap).forEach(id => {
    const el = $(id);
    if (!el) return;

    el.addEventListener("change", e => {
      const settingKey = toggleMap[id];
      appSettings[settingKey] = e.target.checked;

      if (id === "setPrefPop" && e.target.checked) {
        appSettings.prefNiche = false;
      }

      if (id === "setPrefNiche" && e.target.checked) {
        appSettings.prefPop = false;
      }

      saveAppSettings();
      refreshBySettings();
    });
  });

  document.querySelectorAll(".seg-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      appSettings.cardSize = btn.getAttribute("data-val") || "中";
      saveAppSettings();
      refreshBySettings();
    });
  });

  $("clearCollectionBtn")?.addEventListener("click", () => {
    if (confirm("確定要清除所有收藏嗎？")) {
      saveCollection("favorites", []);
      renderCollection();
      renderExploreResults($("exploreSearchInput")?.value || "");
      renderRecommendations();
      updateMemberStats();
      alert("收藏已清空！");
    }
  });

  $("resetAllDataBtn")?.addEventListener("click", () => {
    if (!confirm("確定要把外觀與推薦偏好恢復成預設值嗎？")) return;

    appSettings = { ...DEFAULT_APP_SETTINGS };
    saveAppSettings();
    refreshBySettings();
    alert("設定已恢復預設值。");
  });

  $("saveSettingsBtn")?.addEventListener("click", e => {
    saveAppSettings();
    applyVisualSettings();

    const btn = e.currentTarget;
    const oldText = btn.textContent;
    btn.textContent = "✓ 設定已儲存";
    btn.classList.add("saved");

    setTimeout(() => {
      btn.textContent = oldText || "儲存設定";
      btn.classList.remove("saved");
    }, 1300);
  });
}

function getCurrentRoomCode() {
  return backendRoomCode(localStorage.getItem(ROOM_KEY) || "");
}

async function setCurrentRoomCode(code) {
  const cleanCode = backendRoomCode(code);
  if (!cleanCode) return;

  try {
    await apiRoomGet(cleanCode);
  } catch (_) {
    alert("房間不存在，請確認代碼，或請房主先按「產生新房間」。");
    return;
  }

  stopRoomPoll();
  localStorage.setItem(ROOM_KEY, cleanCode);
  updateRoomUI();
  groupMembers = [];
  groupVotes = {};
  activeMemberId = null;
  saveGroupMembers();
  saveGroupVotes();

  try {
    await refreshRoomFromServer();
  } catch (_) {
    renderMembers();
  }
  startRoomPoll();
  renderGroupTags();
  renderRoleOptions();
  renderRecommendations();
  alert(`已切換到房間：${formatRoomCodeDisplay(cleanCode)}`);
}

function getRoomMembersKey() {
  return `moodluma-group-members-${getCurrentRoomCode()}`;
}

function getRoomVotesKey() {
  return `moodluma-group-votes-${getCurrentRoomCode()}`;
}

function updateRoomUI() {
  const display = formatRoomCodeDisplay(getCurrentRoomCode());
  if ($("roomCode")) {
    $("roomCode").textContent = display;
  }
  if ($("joinRoomInput")) {
    $("joinRoomInput").value = display;
  }
}

function ensureDefaultMembers() {
  if (groupMembers.length) {
    groupMembers = groupMembers.map((member, index) => ({
      ...member,
      role: member.role || `role-${Math.min(index + 1, 5)}`
    }));

    if (!activeMemberId || !groupMembers.some(member => member.id === activeMemberId)) {
      activeMemberId = groupMembers[0]?.id || null;
    }

    saveGroupMembers();
    return;
  }

  groupMembers = [
    { id: "member-a", name: "成員 A", tags: {}, role: "role-1" },
    { id: "member-b", name: "成員 B", tags: {}, role: "role-2" },
    { id: "member-c", name: "成員 C", tags: {}, role: "role-3" }
  ];

  activeMemberId = "member-a";
  saveGroupMembers();
}

function loadGroupMembers() {
  try {
    return JSON.parse(localStorage.getItem(getRoomMembersKey()) || "[]");
  } catch {
    return [];
  }
}

function saveGroupMembers() {
  localStorage.setItem(getRoomMembersKey(), JSON.stringify(groupMembers));
}

function loadGroupVotes() {
  try {
    return JSON.parse(localStorage.getItem(getRoomVotesKey()) || "{}");
  } catch {
    return {};
  }
}

function saveGroupVotes() {
  localStorage.setItem(getRoomVotesKey(), JSON.stringify(groupVotes));
}

async function addMemberFromInput() {
  const input = $("memberNameInput");
  const name = input.value.trim();
  if (!name) return;

  try {
    await apiRoomJoin(getCurrentRoomCode(), name);
    localStorage.setItem(MY_MEMBER_NAME_KEY, name);
    await refreshRoomFromServer();
    const me = groupMembers.find(m => m.name === name);
    if (me) activeMemberId = me.id;
    input.value = "";
    renderMembers();
    renderGroupTags();
    renderRecommendations();
    $("memberList")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    alert(e.message || "加入成員失敗，請確認網路與房間代碼。");
  }
}

async function removeMember(id) {
  const member = groupMembers.find(m => m.id === id);
  groupMembers = groupMembers.filter(m => m.id !== id);
  if (activeMemberId === id) {
    activeMemberId = groupMembers[0]?.id || null;
  }

  Object.keys(groupVotes).forEach(movieId => {
    delete groupVotes[movieId][id];
  });

  saveGroupMembers();
  saveGroupVotes();

  if (member?.name) {
    try {
      await fetch(`${FILMDB_BASE}/api/room/leave`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roomCode: getCurrentRoomCode(), userName: member.name }),
      });
      await refreshRoomFromServer();
    } catch (_) { /* local state already updated */ }
  }

  renderMembers();
  renderGroupTags();
  renderRecommendations();
}

function renderRoleOptions() {
  document.querySelectorAll(".role-option").forEach(btn => {
    const role = btn.dataset.role;
    const activeMember = groupMembers.find(m => m.id === activeMemberId);

    btn.classList.toggle("active", activeMember?.role === role);
  });
}

function setActiveMember(id) {
  activeMemberId = id;
  renderMembers();
  renderRoleOptions();
  updateGroupVoteUI(currentModalMovie);
}

function renameMember(id) {
  const member = groupMembers.find(m => m.id === id);
  if (!member) return;

  const newName = prompt("請輸入新的成員名稱", member.name);
  if (!newName) return;

  const cleanName = newName.trim();
  if (!cleanName) return;

  member.name = cleanName;
  saveGroupMembers();
  renderMembers();
  updateGroupVoteUI(currentModalMovie);
  renderRecommendations();
}

function renderMembers() {
  const box = $("memberList");
  if (!box) return;

  box.innerHTML = "";

  groupMembers.forEach(member => {
    const tagNames = Object.keys(member.tags || {});
    const card = document.createElement("article");

    card.className = `member-card ${member.id === activeMemberId ? "active" : ""}`;

    card.innerHTML = `
      <div class="member-role-wrap">
        <img class="member-role-img" src="roles/${member.role || "role-1"}.png" alt="${escapeHtml(member.name)}的角色">
        <div>
          <h4>${escapeHtml(member.name)}</h4>
          <p>${tagNames.length ? tagNames.slice(0, 4).join("、") : "尚未選擇感覺"}</p>
        </div>
      </div>

      <div class="member-actions">
        <button data-action="active" type="button">切換</button>
        <button data-action="rename" type="button">改名</button>
        <button data-action="clear" type="button">清空</button>
        <button data-action="remove" type="button">移除</button>
      </div>
    `;

    // 點整張成員卡片，也可以切換目前選中的成員
    card.addEventListener("click", () => {
      setActiveMember(member.id);
    });

    card.querySelector('[data-action="active"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      setActiveMember(member.id);
    });

    card.querySelector('[data-action="rename"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      renameMember(member.id);
    });

    card.querySelector('[data-action="clear"]')?.addEventListener("click", (e) => {
      e.stopPropagation();

      member.tags = {};
      saveGroupMembers();

      renderMembers();
      renderGroupTags();
      renderRoleOptions();
      renderRecommendations();
    });

    card.querySelector('[data-action="remove"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      removeMember(member.id);
      renderRoleOptions();
    });

    box.appendChild(card);
  });
}

function getGroupTagMap() {
  const map = new Map();

  groupMembers.forEach(member => {
    Object.values(member.tags || {}).forEach(item => {
      const prev = map.get(item.tag) || { tag: item.tag, weight: 0, count: 0 };
      prev.weight += item.weight || 0.6;
      prev.count += 1;
      map.set(item.tag, prev);
    });
  });

  return map;
}

function renderGroupTags() {
  const box = $("groupTags");
  if (!box) return;

  const tags = [...getGroupTagMap().values()]
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 10);

  if (!tags.length) {
    box.innerHTML = `<span class="group-tag">尚無共同感覺</span>`;
    return;
  }

  box.innerHTML = tags.map(t => `
    <span class="group-tag">${escapeHtml(t.tag)} <small>${t.count}人</small></span>
  `).join("");
}

function computeGroupScore(movie) {
  const tags = [...getGroupTagMap().values()];
  if (!tags.length) return 0;

  const movieText = [
    movie.title,
    movie.desc,
    ...movie.genre,
    ...movie.mood,
    ...movie.mainScene,
    ...movie.subScene
  ].join(" ").toLowerCase();

  let score = 0;
  let max = 0;

  tags.forEach(item => {
    const tag = item.tag.toLowerCase();
    const weight = item.weight || 0.6;
    max += weight;
    if (movieText.includes(tag) || fuzzyTagHit(movie, item.tag)) {
      score += weight;
    }
  });

  return max ? score / max : 0;
}

function computeGroupVoteScore(movie) {
  const votes = groupVotes[movie.id] || {};
  const values = Object.values(votes);
  if (!values.length) return 0;

  let score = 0;
  values.forEach(v => {
    if (v === "want") score += 0.18;
    if (v === "nope") score -= 0.22;
  });

  return score;
}

function setGroupVote(type) {
  if (!currentModalMovie || !activeMemberId) return;
  if (!groupVotes[currentModalMovie.id]) groupVotes[currentModalMovie.id] = {};
  groupVotes[currentModalMovie.id][activeMemberId] = type;
  saveGroupVotes();
  updateGroupVoteUI(currentModalMovie);
  renderRecommendations();
}

function updateGroupVoteUI(movie) {
  const status = $("groupVoteStatus");
  const wantBtn = $("groupWantBtn");
  const nopeBtn = $("groupNopeBtn");
  if (!status || !wantBtn || !nopeBtn || !movie) return;

  const member = groupMembers.find(m => m.id === activeMemberId);
  const vote = groupVotes[movie.id]?.[activeMemberId] || "";

  wantBtn.classList.toggle("active", vote === "want");
  nopeBtn.classList.toggle("active", vote === "nope");

  if (!groupMode) {
    status.textContent = "多人模式尚未開啟，開啟後可讓不同成員投票。";
    return;
  }

  if (!member) {
    status.textContent = "請先新增或選擇一位成員。";
    return;
  }

  if (vote === "want") {
    status.textContent = `${member.name} 已投票：想看這部。`;
  } else if (vote === "nope") {
    status.textContent = `${member.name} 已投票：不想看這部。`;
  } else {
    status.textContent = `目前投票成員：${member.name}`;
  }
}

function renderGroupMovieBadge(movie) {
  if (!groupMode) return "";
  const votes = groupVotes[movie.id] || {};
  const wants = Object.values(votes).filter(v => v === "want").length;
  const nopes = Object.values(votes).filter(v => v === "nope").length;
  const groupScore = Math.round(computeGroupScore(movie) * 100);

  const parts = [];
  if (groupScore > 0) parts.push(`<span class="group-badge">👥 共同 ${groupScore}%</span>`);
  if (wants > 0) parts.push(`<span class="feedback-badge like vote-badge">🙋 ${wants} 想看</span>`);
  if (nopes > 0) parts.push(`<span class="feedback-badge dislike vote-badge bad">🙅 ${nopes} 不想看</span>`);
  return parts.join("");
}


function loadFeedbacks() {
  try {
    return JSON.parse(localStorage.getItem("feelmovie-feedbacks") || "{}");
  } catch {
    return {};
  }
}

function saveFeedbacks() {
  localStorage.setItem("feelmovie-feedbacks", JSON.stringify(feedbacks));
  scheduleUserStatePush();
}

function getFeedback(movie) {
  return feedbacks[movie.id]?.rating || "";
}

function hasWatchedTrailer(movie) {
  return Boolean(feedbacks[movie.id]?.watchedTrailer);
}

function markTrailerWatched(movie) {
  const prev = feedbacks[movie.id] || {};
  feedbacks[movie.id] = {
    ...prev,
    watchedTrailer: true,
    watchedAt: new Date().toISOString()
  };
  saveFeedbacks();
}

function updateTemperaturePreview(value) {
  const temperature = Math.max(0, Math.min(100, Number(value) || 0));
  const tempValue = $("feedbackTemperatureValue");
  const tempFill = $("feedbackTempFill");

  if (tempValue) {
    tempValue.textContent = `${temperature}°`;
  }

  if (tempFill) {
    tempFill.style.width = `${temperature}%`;
  }
}

function getNextRecommendedMovie(currentMovieId) {
  const currentKey = String(currentMovieId || "");
  const criteriaActive = hasRecommendationCriteria();
  const needsPopularity = appSettings.prefPop || appSettings.prefNiche;

  const ratedKeys = new Set(
    Object.keys(feedbacks || {}).map(key => String(key))
  );

  const maxViews = needsPopularity
    ? Math.max(1, ...allMovies.map(movie => Math.max(0, Number(getViewCount(movie) || 0))))
    : 1;

  const scored = allMovies
    .filter(movie => {
      const key = getMovieKey(movie);
      if (key === currentKey) return false;
      if (ratedKeys.has(key)) return false;
      if (!moviePassesPreferenceFilters(movie)) return false;
      return true;
    })
    .map(movie => {
      const score = criteriaActive ? computeScore(movie) : 0;
      const popularityRatio = needsPopularity
        ? Math.max(0, Math.min(1, Number(getViewCount(movie) || 0) / maxViews))
        : 0;

      return {
        movie,
        score,
        rankScore: computeRankingScore(movie, score, popularityRatio)
      };
    })
    .sort((a, b) => {
      const av = getViewCount(a.movie);
      const bv = getViewCount(b.movie);
      return b.rankScore - a.rankScore || bv - av;
    });

  if (criteriaActive) {
    return scored.find(item => item.score > 0) || scored[0] || null;
  }

  return scored[0] || null;
}

function getMovieKey(movie) {
  return String(movie?.id || movie?.title || "").trim();
}

function setTemperatureFeedback(value) {
  if (!currentModalMovie) return;

  const movieId = getMovieKey(currentModalMovie);
  const temperature = Math.max(0, Math.min(100, Number(value) || 50));

  const type = temperature >= 50 ? "like" : "dislike";

  const prev = feedbacks[movieId] || {};
  feedbacks[movieId] = {
    ...prev,
    rating: type,
    temperature,
    ratedAt: new Date().toISOString()
  };

  saveFeedbacks();
  updateFeedbackUI(currentModalMovie);
  renderRecommendations();

  const nextBest = getNextRecommendedMovie(movieId);

  if (nextBest) {
    setTimeout(() => {
      openModal(nextBest.movie, nextBest.score);
    }, 500);
  } else {
    setTimeout(() => {
      closeModal();
      alert("目前已經沒有更多未評價的推薦電影。");
    }, 500);
  }
}

function setFeedback(type) {
  if (!currentModalMovie) return;

  const movieId = currentModalMovie.id;

  const prev = feedbacks[movieId] || {};
  feedbacks[movieId] = {
    ...prev,
    rating: type,
    ratedAt: new Date().toISOString()
  };
  saveFeedbacks();
  updateFeedbackUI(currentModalMovie);

  if (type === "dislike") {
    const scored = allMovies
      .map(movie => ({ movie, score: computeScore(movie) }))
      .sort((a, b) => {
        const av = getViewCount(a.movie);
        const bv = getViewCount(b.movie);
        return b.score - a.score || bv - av;
      });
    const nextBest = scored.find(x => x.movie.id !== movieId);

    if (nextBest && nextBest.score > 0) {
      openModal(nextBest.movie, nextBest.score);
    } else {
      closeModal();
      renderRecommendations();
    }
    
  } else {
    renderRecommendations();
  }
}

function updateFeedbackUI(movie) {
  const tempInput = $("feedbackTemperature");
  const status = $("feedbackStatus");

  if (!status) return;

  const feedback = feedbacks[getMovieKey(movie)] || {};
  const rating = feedback.rating || "";

  const temperature = typeof feedback.temperature === "number"
    ? feedback.temperature
    : rating === "like"
      ? 85
      : rating === "dislike"
        ? 25
        : 50;

  const watched = hasWatchedTrailer(movie);

  if (tempInput) {
    tempInput.value = temperature;
  }

  updateTemperaturePreview(temperature);

  if (rating === "like") {
    status.textContent = `你給了 ${temperature}° 高溫好評：之後會更常推薦相似氛圍的電影。`;
  } else if (rating === "dislike") {
    status.textContent = `你給了 ${temperature}° 低溫評價：之後會降低相似電影的推薦權重。`;
  } else if (watched) {
    status.textContent = "你已開啟預告片，可以拖曳溫度計留下評價。";
  } else {
    status.textContent = "尚未評分。看完預告後，可以拖曳溫度計留下回饋。";
  }
}

function renderFeedbackBadge(movie) {
  const feedback = feedbacks[movie.id] || {};
  const rating = feedback.rating || "";
  const temperature = typeof feedback.temperature === "number"
    ? feedback.temperature
    : rating === "like"
      ? 85
      : rating === "dislike"
        ? 20
        : "";

  if (rating === "like") {
    return `<span class="feedback-badge like">🌡 ${temperature}° 高溫好評</span>`;
  }

  if (rating === "dislike") {
    return `<span class="feedback-badge dislike">🌡 ${temperature}° 低溫評價</span>`;
  }

  return "";
}

function loadViews() {
  try {
    return JSON.parse(localStorage.getItem("feelmovie-view-counts") || "{}");
  } catch {
    return {};
  }
}

function saveViews() {
  localStorage.setItem("feelmovie-view-counts", JSON.stringify(viewCounts));
  scheduleUserStatePush();
}

function getViewCount(movie) {
  return Number(viewCounts[movie.id] || 0) + Number(movie.views || 0);
}

function incrementView(movie) {
  viewCounts[movie.id] = Number(viewCounts[movie.id] || 0) + 1;
  saveViews();  cachedPopularityMaxViews = null;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  }[m]));
}

function safeAttr(s) {
  return String(s || "").replace(/'/g, "%27").replace(/\)/g, "%29");
}

document.addEventListener("DOMContentLoaded", () => {
  const menuToggle = document.getElementById("menuToggle");
  const sideNav = document.querySelector(".side-nav");

  if (!menuToggle || !sideNav) return;

  menuToggle.addEventListener("click", () => {
    const isOpen = sideNav.classList.toggle("show");

    menuToggle.setAttribute("aria-expanded", String(isOpen));
  });

  sideNav.querySelectorAll(".nav-btn").forEach((button) => {
    button.addEventListener("click", () => {
      if (window.innerWidth <= 768) {
        sideNav.classList.remove("show");
        menuToggle.setAttribute("aria-expanded", "false");
      }
    });
  });
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./service-worker.js")
      .then(() => {
        console.log("Service Worker 註冊成功");
      })
      .catch((error) => {
        console.error("Service Worker 註冊失敗：", error);
      });
  });
}

let deferredInstallPrompt = null;

const installAppBtn = document.getElementById("installAppBtn");

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;

  if (installAppBtn) {
    installAppBtn.style.display = "inline-flex";
  }
});

if (installAppBtn) {
  installAppBtn.addEventListener("click", async () => {
    const isIOS =
      /iphone|ipad|ipod/i.test(window.navigator.userAgent);

    const isStandalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;

    if (isStandalone) {
      alert("Moodluma 已經安裝在這台裝置上。");
      return;
    }

    if (isIOS) {
      alert(
        "iPhone 安裝方式：\n\n" +
        "1. 請使用 Safari 開啟網站\n" +
        "2. 點擊下方的「分享」按鈕\n" +
        "3. 選擇「加入主畫面」\n" +
        "4. 點擊「加入」完成安裝"
      );
      return;
    }

    if (!deferredInstallPrompt) {
      alert(
        "目前無法直接顯示安裝視窗。\n\n" +
        "請使用 Chrome 或 Edge 開啟網站，" +
        "並確認網站已透過 HTTPS 部署。"
      );
      return;
    }

    deferredInstallPrompt.prompt();

    const choice = await deferredInstallPrompt.userChoice;

    if (choice.outcome === "accepted") {
      console.log("使用者接受安裝 Moodluma");
    } else {
      console.log("使用者取消安裝 Moodluma");
    }

    deferredInstallPrompt = null;
  });
}

window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;

  if (installAppBtn) {
    installAppBtn.innerHTML = `<span class="icon-label"><svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"/></svg><span>Moodluma 已安裝</span></span>`;
    installAppBtn.disabled = true;
  }
});
