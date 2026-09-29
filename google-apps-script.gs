/**
 * 📊 Jarvis → Google Sheet (วางใน script.google.com)
 *
 * วิธีติดตั้ง (มือถือก็ทำได้):
 * 1) สร้าง Google Sheet ใหม่ (เช่นชื่อ "งาน Jarvis") → เปิดลิงก์ชีต
 *    ก๊อป "รหัสชีต" = ส่วนใน URL ระหว่าง /d/ กับ /edit
 * 2) เปิด https://script.google.com (Chrome แนะนำ ถ้าหน้าเพี้ยนให้เลือก
 *    เมนู ⋮ → เว็บไซต์เดสก์ท็อป) → New project → ลบโค้ดเดิม วางไฟล์นี้ทั้งหมด
 * 3) แก้บรรทัด SHEET_ID ด้านล่าง = รหัสชีตที่ก๊อปไว้
 * 4) Deploy → New deployment → เลือกชนิด Web app
 *    - Execute as: Me
 *    - Who has access: Anyone   ← สำคัญ! ต้องเป็น Anyone
 *    → Deploy → อนุญาตสิทธิ์ → ก๊อป "Web app URL"
 * 5) ใน Discord พิมพ์ /sheet → กด 🔗 ตั้งลิงก์ → วาง URL → กด 🧪 ทดสอบ
 */

const SHEET_ID = "วางรหัสชีตตรงนี้";

function doGet(e) {
  var d = {};
  try { d = JSON.parse(e.parameter.payload); } catch (err) {}
  return handle(d);
}

function doPost(e) {
  var d = {};
  try { d = JSON.parse(e.postData.contents); } catch (err) {}
  return handle(d);
}

function handle(d) {
  var out = { ok: true };
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(20000);
    var ss = SpreadsheetApp.openById(SHEET_ID);

    if (d.action === "ping") {
      getSheet(ss, "log").appendRow(["ping", new Date()]);
      out.msg = "pong";

    } else if (d.action === "append" && d.sheet && d.row) {
      getSheet(ss, d.sheet).appendRow(d.row);
      out.msg = "เพิ่ม 1 แถว";

    } else if (d.action === "sync" && d.sheet && d.head && d.rows) {
      var sh = getSheet(ss, d.sheet);
      sh.clearContents();
      sh.getRange(1, 1, 1, d.head.length).setValues([d.head]);
      if (d.rows.length > 0) {
        sh.getRange(2, 1, d.rows.length, d.head.length).setValues(d.rows);
      }
      sh.setFrozenRows(1);
      out.msg = "ส่ง " + d.rows.length + " แถว";

    } else {
      out.ok = false;
      out.msg = "ไม่รู้จักคำสั่ง";
    }
    lock.releaseLock();
  } catch (err) {
    out.ok = false;
    out.msg = String(err);
    try { lock.releaseLock(); } catch (e2) {}
  }
  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON);
}

function getSheet(ss, name) {
  var sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  return sh;
}
