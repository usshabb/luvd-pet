// Google Apps Script side of the subscriber backup (see sheet_sync.py).
// Lives in the "LUVD NYC Subscribers" spreadsheet: Extensions → Apps Script,
// paste this file, then Deploy → New deployment → Web app, executing as you,
// accessible to "Anyone". The deployment URL is the secret the app posts to —
// it goes in Fly as SHEET_WEBHOOK_URL and nowhere else.
//
// Each POST carries the entire subscribers table and this rewrites the sheet
// from scratch, so the sheet always equals the database and a missed webhook
// heals on the next sync.
//
// One tab with a city column, rather than a tab per city. sheet_sync.py has
// been sending each row's city for a while and this ignored it, so the backup
// could not tell a New York subscriber from a Los Angeles one.
//
// A column rather than tabs on purpose. A city whose subscribers all leave
// sends no rows at all, so a script that writes tab-by-tab from the rows it
// received would leave that tab holding addresses that are no longer on the
// list — a stale copy that looks current. Rewriting one sheet every time
// cannot drift that way, and sorting or filtering by city is one click.

var HEADERS = ["email", "city", "active", "created"];

function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheets()[0];

  // Fill the defaults BEFORE sorting. Sorting on `s.city || ""` while writing
  // `s.city || "NYC"` sorts a row missing its city under the empty string and
  // then prints NYC next to it, which scatters those rows through the sheet
  // instead of grouping them. One normalised value, used for both.
  var subs = (data.subscribers || []).map(function (s) {
    return {
      email: s.email,
      city: s.city || "NYC",
      active: s.active,
      created: s.created || ""
    };
  });

  // City first, then signup time, so the two lists read as two blocks without
  // anybody having to sort. The server already orders it this way; doing it
  // here too means the sheet is right even against an older app.
  subs.sort(function (a, b) {
    if (a.city !== b.city) return a.city < b.city ? -1 : 1;
    return a.created < b.created ? -1 : 1;
  });

  var rows = [HEADERS];
  subs.forEach(function (s) {
    rows.push([s.email, s.city, s.active, s.created]);
  });

  // clear(), not clearContents(): the sheet gets one column wider than it used
  // to be, and clearContents leaves the old header formatting sitting on a
  // column that now means something else.
  sheet.clear();
  sheet.getRange(1, 1, rows.length, HEADERS.length).setValues(rows);
  sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold");
  sheet.setFrozenRows(1);

  // A count per city in the response, so a sync can be spot-checked from the
  // execution log without opening the spreadsheet.
  var byCity = {};
  subs.forEach(function (s) {
    byCity[s.city] = (byCity[s.city] || 0) + 1;
  });

  return ContentService.createTextOutput(
    JSON.stringify({ ok: true, count: subs.length, by_city: byCity })
  ).setMimeType(ContentService.MimeType.JSON);
}
