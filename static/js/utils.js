// static/js/utils.js

function escapeHTML(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatDateGerman(isoDateStr) {
  if (!isoDateStr) return "(kein Datum)";
  const date = new Date(isoDateStr);
  return date.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function initDataTable(selector, url, columns, options = {}) {
  const tableElement = $(selector);
  const settings = {
    ajax: {
      url: url,
      dataSrc: ''
    },
    columns: columns,
    language: {
      url: DATATABLES_LANG_URL
    },
    ...options
  };
  return tableElement.DataTable(settings);
}