/**
 * FilmDB 寄信中繼（Google Apps Script）
 *
 * 設定步驟：
 * 1. 用要當寄件者的 Gmail 開啟 https://script.google.com
 * 2. 新增專案 → 貼上本檔全部內容
 * 3. 把 MAIL_SECRET 改成一組自己的密語（之後寫進試算表）
 * 4. 部署 → 新增部署 → 類型選「網頁應用程式」
 *    - 執行身分：我
 *    - 具有存取權的使用者：任何人
 * 5. 授權後複製「網頁應用程式網址」
 * 6. 在 FilmDB 試算表 config 工作表新增：
 *      A: mail_webhook_url      B:（貼上網址）
 *      A: mail_webhook_secret   B:（與下方 MAIL_SECRET 相同）
 *      A: app_login_url         B: https://filmdb-68z4.onrender.com  （可選）
 *
 * 免費 Gmail 每天約可寄 100 封；寄件顯示為你的 Gmail。
 */

var MAIL_SECRET = "請改成你的密語";

function doPost(e) {
  try {
    var raw = (e && e.postData && e.postData.contents) ? e.postData.contents : "{}";
    var data = JSON.parse(raw);
    if (!data.secret || data.secret !== MAIL_SECRET) {
      return jsonOut({ ok: false, error: "secret 不符" });
    }
    var to = String(data.to || "").trim();
    var subject = String(data.subject || "").trim();
    var text = String(data.text || "");
    var html = String(data.html || "");
    if (!to || !subject) {
      return jsonOut({ ok: false, error: "缺少 to 或 subject" });
    }
    var options = {
      to: to,
      subject: subject,
      body: text || " ",
      name: String(data.fromName || "FilmDB"),
    };
    if (html) {
      options.htmlBody = html;
    }
    MailApp.sendEmail(options);
    return jsonOut({ ok: true, id: "appscript:" + new Date().toISOString() });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

function doGet() {
  return jsonOut({ ok: true, service: "FilmDB mail relay" });
}

function jsonOut(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
