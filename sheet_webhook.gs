// Google Apps Script side of the subscriber backup (see sheet_sync.py).
// Lives in the "LUVD NYC Subscribers" spreadsheet: Extensions → Apps Script,
// paste this file, then Deploy → New deployment → Web app, executing as you,
// accessible to "Anyone". The deployment URL is the secret the app posts to —
// it goes in Fly as SHEET_WEBHOOK_URL and nowhere else.
//
// Each POST carries the entire subscribers table and this rewrites the sheet
// from scratch, so the sheet always equals the database and a missed webhook
// heals on the next sync.

function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheets()[0];
  var rows = [["email", "active", "created"]];
  data.subscribers.forEach(function (s) {
    rows.push([s.email, s.active, s.created]);
  });
  sheet.clearContents();
  sheet.getRange(1, 1, rows.length, 3).setValues(rows);
  return ContentService.createTextOutput(
    JSON.stringify({ ok: true, count: data.subscribers.length })
  ).setMimeType(ContentService.MimeType.JSON);
}
