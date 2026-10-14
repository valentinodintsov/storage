/*
 * Формирование усиленной ЭП (CAdES-BES, откреплённая) через КриптоПро ЭЦП Browser plug-in.
 * Требуется: КриптоПро CSP, расширение браузера и скрипт cadesplugin_api.js,
 * который следует разместить в /static/vendor/cadesplugin_api.js (распространяется КриптоПро).
 */
(function () {
  "use strict";
  var form = document.getElementById("sign-form");
  if (!form || form.dataset.provider !== "cades") return;
  var select = document.getElementById("cert-select");
  var status = document.getElementById("cades-status");
  var certs = [];

  function fail(message) {
    status.textContent = message;
    status.classList.add("error-text");
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function listCertificates() {
    return cadesplugin.async_spawn(function* () {
      var store = yield cadesplugin.CreateObjectAsync("CAdESCOM.Store");
      yield store.Open(cadesplugin.CAPICOM_CURRENT_USER_STORE, cadesplugin.CAPICOM_MY_STORE,
                       cadesplugin.CAPICOM_STORE_OPEN_MAXIMUM_ALLOWED);
      var all = yield store.Certificates;
      var valid = yield all.Find(cadesplugin.CAPICOM_CERTIFICATE_FIND_TIME_VALID);
      var count = yield valid.Count;
      var result = [];
      for (var i = 1; i <= count; i++) {
        var cert = yield valid.Item(i);
        result.push({
          cert: cert,
          subject: yield cert.SubjectName,
          thumbprint: yield cert.Thumbprint,
          validTo: yield cert.ValidToDate
        });
      }
      yield store.Close();
      return result;
    });
  }

  function sign(cert, contentBase64) {
    return cadesplugin.async_spawn(function* () {
      var signer = yield cadesplugin.CreateObjectAsync("CAdESCOM.CPSigner");
      yield signer.propset_Certificate(cert);
      yield signer.propset_CheckCertificate(true);
      var data = yield cadesplugin.CreateObjectAsync("CAdESCOM.CadesSignedData");
      yield data.propset_ContentEncoding(cadesplugin.CADESCOM_BASE64_TO_BINARY);
      yield data.propset_Content(contentBase64);
      return yield data.SignCades(signer, cadesplugin.CADESCOM_CADES_BES, true);
    });
  }

  function cn(subject) {
    var m = /CN=([^,]+)/.exec(subject);
    return m ? m[1] : subject;
  }

  (window.cadesplugin ? Promise.resolve() : loadScript("/static/vendor/cadesplugin_api.js"))
    .then(function () { return window.cadesplugin; })
    .then(listCertificates)
    .then(function (list) {
      certs = list;
      select.innerHTML = "";
      if (!list.length) { fail("Не найдено действующих сертификатов ЭП"); return; }
      list.forEach(function (c, i) {
        var o = document.createElement("option");
        o.value = String(i);
        o.textContent = cn(c.subject) + " (до " + new Date(c.validTo).toLocaleDateString("ru-RU") + ")";
        select.appendChild(o);
      });
      status.textContent = "Выберите сертификат и нажмите «Подписать ЭП».";
    })
    .catch(function () { fail("КриптоПро ЭЦП Browser plug-in недоступен. Установите КриптоПро CSP и расширение браузера."); });

  form.addEventListener("submit", function (e) {
    if (form.elements.signature.value) return;
    e.preventDefault();
    var c = certs[Number(select.value)];
    if (!c) { fail("Выберите сертификат"); return; }
    status.textContent = "Подписание…";
    fetch("/api/v1/waybills/" + form.dataset.waybill + "/sign-document", { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (doc) { return sign(c.cert, doc.content_base64); })
      .then(function (signature) {
        form.elements.signature.value = signature.replace(/\s+/g, "");
        form.elements.certificate.value = "Сертификат: " + c.subject + "; отпечаток " + c.thumbprint;
        form.submit();
      })
      .catch(function (err) { fail("Ошибка подписания: " + (err && err.message ? err.message : err)); });
  });
})();
