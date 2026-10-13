"use strict";
(() => {
  let flow = new URLSearchParams(location.hash.slice(1)).get("flow");
  history.replaceState(null, "", location.pathname);
  const form = document.querySelector("#login-form");
  const mobile = document.querySelector("#mobile");
  const code = document.querySelector("#code");
  const captcha = document.querySelector("#captcha");
  const captchaSection = document.querySelector("#captcha-section");
  const captchaImage = document.querySelector("#captcha-image");
  const send = document.querySelector("#send-sms");
  const login = document.querySelector("#login-button");
  const status = document.querySelector("#status");
  let busy = false;
  let done = false;
  let until = 0;
  let challenge = false;
  function show(message, kind = "info") {
    status.textContent = message;
    status.dataset.kind = kind;
  }
  function refresh() {
    const seconds = Math.max(0, Math.ceil((until - Date.now()) / 1000));
    send.textContent = seconds && !challenge ? `${seconds} 秒后重发` : "发送验证码";
    send.disabled = busy || done || (!challenge && seconds > 0);
    login.disabled = busy || done;
    mobile.disabled = busy || done || challenge;
    code.disabled = captcha.disabled = busy || done;
  }
  function stop(message, success = false) {
    done = true;
    flow = null;
    form.reset();
    captchaImage.removeAttribute("src");
    captchaSection.hidden = true;
    form.hidden = true;
    show(message, success ? "success" : "error");
    clearInterval(timer);
  }
  async function post(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Meiju-Flow": flow},
        body: JSON.stringify(body),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        signal: controller.signal,
      });
      const result = await response.json();
      if (!response.ok) {
        if (["flow_expired", "invalid_flow", "already_authenticated"].includes(result.code)) {
          stop(result.message || "登录链接已失效，请重新发起登录。");
        }
        if (result.retry_after) until = Date.now() + result.retry_after * 1000;
        if (result.reset_captcha || result.code === "captcha_expired" || result.code === "sms_cooldown") {
          challenge = false;
          captchaSection.hidden = true;
          captcha.value = "";
          captchaImage.removeAttribute("src");
        }
        throw new Error(result.message || "请求未完成，请稍后重试。");
      }
      return result;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("服务响应超时，结果暂未确认；请稍后重试。");
      if (error instanceof TypeError) throw new Error("无法连接本机服务，请确认 MCP 服务仍在运行，再重新打开登录链接。");
      if (error instanceof SyntaxError) throw new Error("本机服务返回异常，请重新发起登录。");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
  send.addEventListener("click", async () => {
    if (busy || done || !mobile.reportValidity()) return;
    if (challenge && !/^[A-Za-z0-9]{1,16}$/.test(captcha.value.trim())) {
      show("请先填写图形验证码。", "error");
      captcha.focus();
      return;
    }
    busy = true;
    refresh();
    show("正在请求验证码…");
    try {
      const body = {mobile: mobile.value.trim()};
      if (challenge) body.captcha = captcha.value.trim();
      const result = await post("/api/sms", body);
      if (result.status === "captcha_required") {
        challenge = true;
        captchaSection.hidden = false;
        captchaImage.src = result.captcha_data_url;
        captcha.value = "";
        show("请填写图形验证码，再次点击「发送验证码」。");
      } else if (result.status === "sms_sent") {
        challenge = false;
        captchaSection.hidden = true;
        captcha.value = "";
        captchaImage.removeAttribute("src");
        until = Date.now() + result.retry_after * 1000;
        show("验证码已发送，请查看手机短信。");
      }
    } catch (error) {
      show(error.message, "error");
    } finally {
      busy = false;
      refresh();
      if (!done) (challenge ? captcha : code).focus();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || done || !form.reportValidity()) return;
    busy = true;
    refresh();
    show("正在登录美居…");
    try {
      const result = await post("/api/login", {mobile: mobile.value.trim(), code: code.value.trim()});
      if (result.status === "authenticated") stop("美居登录成功。返回 AI 客户端即可使用，可以关闭此页面。", true);
    } catch (error) {
      show(error.message, "error");
    } finally {
      code.value = "";
      busy = false;
      refresh();
    }
  });
  const timer = setInterval(refresh, 250);
  if (!flow) stop("登录链接不完整或已使用，请返回 AI 客户端重新发起登录。");
  refresh();
})();
