var HEADERS = ["email", "city", "active", "created"];

function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];

  var subs = (data.subscribers || []).map(function (s) {
    return {
      email: s.email,
      city: s.city || "NYC",
      active: s.active,
      created: s.created || ""
    };
  });

  subs.sort(function (a, b) {
    if (a.city !== b.city) return a.city < b.city ? -1 : 1;
    return a.created < b.created ? -1 : 1;
  });

  var rows = [HEADERS];
  subs.forEach(function (s) {
    rows.push([s.email, s.city, s.active ? "yes" : "no", s.created]);
  });

  sheet.clear();
  sheet.getRange(1, 1, rows.length, 4)
    .setNumberFormat("@")
    .setValues(rows);
  sheet.getRange(1, 1, 1, 4).setFontWeight("bold");
  sheet.setFrozenRows(1);

  var byCity = {};
  subs.forEach(function (s) {
    byCity[s.city] = (byCity[s.city] || 0) + 1;
  });

  return ContentService.createTextOutput(
    JSON.stringify({ ok: true, count: subs.length, by_city: byCity })
  ).setMimeType(ContentService.MimeType.JSON);
}
