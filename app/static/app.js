(function () {
  "use strict";

  // Меню на мобильных устройствах
  document.querySelectorAll("[data-toggle-nav]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.getElementById("nav").classList.toggle("open");
    });
  });

  // Клик по строке таблицы открывает карточку
  document.querySelectorAll("tr[data-href]").forEach(function (row) {
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, select, label")) return;
      window.location = row.dataset.href;
    });
  });

  // Подтверждение опасных действий
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // Форма позиции: поля, специфичные для вида учёта (лицензии, техника)
  document.querySelectorAll("form[data-kind-form]").forEach(function (form) {
    var kind = form.querySelector("[name=kind]");
    if (!kind) return;
    var category = form.querySelector("[name=category_id]");
    var categoryOptions = category ? Array.from(category.options) : [];
    var kindLabels = {};
    Array.from(kind.options).forEach(function (o) { kindLabels[o.value] = o.textContent; });
    function apply() {
      form.querySelectorAll("[data-kinds]").forEach(function (el) {
        el.hidden = el.dataset.kinds.split(" ").indexOf(kind.value) === -1;
      });
      // в списке категорий оставляем только категории выбранного вида
      categoryOptions.forEach(function (o) {
        var match = !o.value || o.textContent.indexOf(kindLabels[kind.value] + ":") === 0;
        o.hidden = !match;
        if (!match && o.selected) category.value = "";
      });
    }
    kind.addEventListener("change", apply);
    apply();
  });

  // Накладная: перестроение списка позиций при смене вида операции, организации или сдающего
  var wbForm = document.getElementById("waybill-form");
  if (wbForm) {
    wbForm.querySelectorAll("[data-reload]").forEach(function (el) {
      el.addEventListener("change", function () {
        if (el.name === "type") {
          wbForm.querySelector("[name=sender_id]").value = "";
          wbForm.querySelector("[name=receiver_id]").value = "";
          wbForm.querySelectorAll("[name=item_ids]").forEach(function (c) { c.checked = false; });
        }
        wbForm.querySelector("[name=reload]").value = "1";
        wbForm.noValidate = true;
        wbForm.submit();
      });
    });
    var counter = document.getElementById("selected-count");
    var updateCount = function () {
      var n = wbForm.querySelectorAll("[name=item_ids]:checked").length;
      if (counter) counter.textContent = n ? "выбрано: " + n : "";
    };
    wbForm.addEventListener("change", updateCount);
    updateCount();
    var all = wbForm.querySelector("[data-check-all]");
    if (all) {
      all.addEventListener("change", function () {
        wbForm.querySelectorAll("tbody tr:not([hidden]) [name=item_ids]").forEach(function (c) { c.checked = all.checked; });
        updateCount();
      });
    }
  }

  // Быстрый фильтр строк таблицы
  document.querySelectorAll("[data-filter-table]").forEach(function (input) {
    var table = document.querySelector(input.dataset.filterTable);
    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase();
      table.querySelectorAll("tbody tr").forEach(function (tr) {
        tr.hidden = q && tr.textContent.toLowerCase().indexOf(q) === -1;
      });
    });
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });
  });
})();
