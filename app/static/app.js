"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const api = async (url, options = {}) => {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "連線失敗，請再試一次。");
  return payload;
};

function renderQuestions(questions, board) {
  board.replaceChildren();
  const bundles = new Map();
  for (const question of questions) {
    const key = question.bundle_id || question.id;
    if (!bundles.has(key)) bundles.set(key, []);
    bundles.get(key).push(question);
  }
  for (const [bundleId, members] of bundles) {
    const card = document.createElement("section");
    card.className = "question-card";
    card.dataset.bundleId = bundleId;
    const heading = document.createElement("h2");
    heading.textContent = members.length > 1 ? `題組：${members.map(q => q.id).join("、")}` : members[0].id;
    card.append(heading);
    for (const question of members) {
      const questionBlock = document.createElement("div");
      questionBlock.className = "question-block";
      if (members.length > 1) {
        const label = document.createElement("h3");
        label.textContent = question.id;
        questionBlock.append(label);
      }
      for (const slot of question.slots) {
        const label = document.createElement("label");
        label.className = "answer-field";
        const suffix = slot.marker ? slot.marker : "";
        label.textContent = `${question.id}${suffix}`;
        const input = document.createElement("input");
        input.type = "text";
        input.name = slot.id;
        input.dataset.slotId = slot.id;
        input.autocomplete = "off";
        input.disabled = true;
        label.append(input);
        questionBlock.append(label);
      }
      card.append(questionBlock);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary submit-bundle";
    button.textContent = members.length > 1 ? "整組送出" : "送出答案";
    button.dataset.bundleId = bundleId;
    button.disabled = true;
    card.append(button);
    board.append(card);
  }
}

function parseBundles(text) {
  return text.split("\n").map(line => line.trim()).filter(Boolean).map(line => {
    const ids = line.split(/[，,\s]+/).filter(Boolean).map(value => value.toUpperCase().replace(/^([0-9])/, "Q$1"));
    if (ids.length < 2 || ids.some(id => !/^Q\d+$/.test(id))) throw new Error("題組請以 Q3,Q4 格式輸入，每行至少兩題。");
    return ids;
  });
}

function initTeacher() {
  const form = $("#create-room-form");
  if (!form) return;
  restoreTeacher();
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const message = $("#teacher-message");
    message.textContent = "建立房間中…";
    try {
      const data = new FormData(form);
      data.delete("bundles");
      data.set("question_bundles", JSON.stringify(parseBundles(form.elements.bundles.value)));
      if (!form.elements.max_wins.value) data.delete("max_wins");
      const room = await api("/api/rooms", { method: "POST", body: data });
      sessionStorage.setItem("quiz-teacher", JSON.stringify({roomId: room.room_id, token: room.teacher_token, projectionUrl: room.projection_url}));
      showTeacherRoom(room.room_id, room.projection_url);
      message.textContent = `房間已建立，共 ${room.question_count} 題。`;
      form.hidden = true;
      await refreshGroups();
      connectRoom("teacher", {roomId: room.room_id, token: room.teacher_token});
    } catch (error) {
      message.textContent = error.message;
    }
  });
  $("#start-race")?.addEventListener("click", () => changePhase("start"));
  $("#end-race")?.addEventListener("click", () => changePhase("end"));
  $("#export-csv")?.addEventListener("click", () => downloadTeacherFile("history.csv", room => `/api/rooms/${encodeURIComponent(room.roomId)}/export/history.csv`));
  $("#export-notes")?.addEventListener("click", () => downloadTeacherFile("guided-notes.xlsx", room => `/api/rooms/${encodeURIComponent(room.roomId)}/export/guided-notes.xlsx`));
}

async function downloadTeacherFile(name, urlFor) {
  const room = JSON.parse(sessionStorage.getItem("quiz-teacher") || "null");
  if (!room) return;
  const response = await fetch(urlFor(room), {headers: {"X-Teacher-Token": room.token}});
  if (!response.ok) { document.querySelector("#teacher-message").textContent = "匯出失敗。"; return; }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob()); link.download = room.roomId + "-" + name;
  link.click(); URL.revokeObjectURL(link.href);
}

function showTeacherRoom(roomId, projectionUrl) {
  $("#room-code").textContent = roomId;
  const studentLink = $("#student-link");
  studentLink.href = `${location.origin}/student`;
  studentLink.textContent = studentLink.href;
  const projectionLink = $("#projection-link");
  projectionLink.href = `${location.origin}${projectionUrl}`;
  projectionLink.textContent = projectionLink.href;
  $("#created-room").hidden = false;
  $("#export-csv").disabled = false;
  $("#export-notes").disabled = false;
  if ($("#create-room-form")) $("#create-room-form").hidden = true;
}

function restoreTeacher() {
  const teacher = JSON.parse(sessionStorage.getItem("quiz-teacher") || "null");
  if (!teacher) return;
  showTeacherRoom(teacher.roomId, teacher.projectionUrl || "");
  refreshGroups();
  connectRoom("teacher", teacher);
}

async function refreshGroups() {
  const room = JSON.parse(sessionStorage.getItem("quiz-teacher") || "null");
  if (!room) return;
  try {
    const result = await api(`/api/rooms/${encodeURIComponent(room.roomId)}/groups`, {
      headers: {"X-Teacher-Token": room.token},
    });
    const list = $("#group-list");
    list.replaceChildren();
    for (const group of result.groups) {
      const item = document.createElement("li");
      item.textContent = group.name;
      list.append(item);
    }
    if (!result.groups.length) list.innerHTML = "<li>尚無組別</li>";
  } catch (_) {
    // A previous room's session can expire; no sensitive token is shown in the UI.
  }
}

function setTeacherPhase(status) {
  const start = $("#start-race");
  const end = $("#end-race");
  if (!start || !end) return;
  start.disabled = status !== "waiting";
  end.disabled = status !== "active";
  window.quizPhase = status;
}

async function changePhase(action) {
  const teacher = JSON.parse(sessionStorage.getItem("quiz-teacher") || "null");
  if (!teacher) return;
  const result = await api(`/api/rooms/${encodeURIComponent(teacher.roomId)}/${action}`, {
    method: "POST",
    headers: {"X-Teacher-Token": teacher.token},
  });
  setTeacherPhase(result.status);
}

function initStudent() {
  const form = $("#join-room-form");
  if (!form) return;
  const saved = JSON.parse(sessionStorage.getItem("quiz-group") || "null");
  if (saved) {
    form.elements.room_id.value = saved.roomId;
    form.elements.group_name.value = saved.groupName;
    joinRoom(saved.roomId, saved.groupName, saved.token).catch(() => sessionStorage.removeItem("quiz-group"));
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    await joinRoom(form.elements.room_id.value.trim().toUpperCase(), form.elements.group_name.value.trim());
  });
}

async function joinRoom(roomId, groupName, token = null) {
  const message = $("#student-message");
  message.textContent = "加入房間中…";
  try {
    const joined = await api(`/api/rooms/${encodeURIComponent(roomId)}/join`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({group_name: groupName, group_token: token}),
    });
    const saved = {roomId, groupName: joined.group_name, groupId: joined.group_id, token: joined.group_token};
    sessionStorage.setItem("quiz-group", JSON.stringify(saved));
    const room = await api(`/api/rooms/${encodeURIComponent(roomId)}/questions`);
    $("#team-label").textContent = joined.group_name;
    $("#phase-label").textContent = room.status === "active" ? "搶答進行中" : "等待搶答";
    renderQuestions(room.questions, $("#answer-board"));
    setStudentPhase(room.status);
    $("#student-room").hidden = false;
    $("#join-room-form").hidden = true;
    message.textContent = "已加入房間。";
    window.quizRoom = { ...saved, status: room.status };
    connectRoom("student", saved);
  } catch (error) {
    message.textContent = error.message;
  }
}

function setStudentPhase(status) {
  const phase = $("#phase-label");
  if (!phase) return;
  phase.textContent = status === "active" ? "搶答進行中" : status === "ended" ? "搶答已結束" : "等待搶答";
  const active = status === "active";
  $("#answer-board")?.querySelectorAll("input, .submit-bundle").forEach(control => { control.disabled = !active; });
  window.quizRoom = {...(window.quizRoom || {}), status};
}

function renderTeacherProgress(progress) {
  const board = document.querySelector("#teacher-progress");
  if (!board) return;
  board.replaceChildren();
  for (const entry of progress || []) {
    const row = document.createElement("article"); row.className = "question-card";
    const text = document.createElement("p");
    text.textContent = entry.answers.map(a => a.question).join("、") + " 第 " + entry.rank + " 名｜" + entry.group_name + "｜" + entry.answers.map(a => a.answer).join(" / ");
    const reject = document.createElement("button"); reject.type = "button"; reject.textContent = entry.review_status === "rejected" ? "已駁回" : "駁回／無效"; reject.disabled = entry.review_status === "rejected";
    reject.addEventListener("click", async () => {
      const teacher = JSON.parse(sessionStorage.getItem("quiz-teacher") || "null");
      const url = "/api/rooms/" + encodeURIComponent(teacher.roomId) + "/submissions/" + encodeURIComponent(entry.submission_id) + "/reject";
      const result = await api(url, {method: "POST", headers: {"Content-Type": "application/json", "X-Teacher-Token": teacher.token}, body: JSON.stringify({})});
      renderTeacherProgress(result.progress); showResults(result);
    });
    row.append(text, reject); board.append(row);
  }
}

function showResults(result) {
  const board = document.querySelector("#results-board") || document.querySelector("#teacher-results") || document.querySelector("#projector-winners");
  if (!board) return;
  board.replaceChildren(); board.hidden = false;
  for (const question of result.questions || []) {
    const winner = (result.winners || {})[question.id];
    const row = document.createElement("p");
    row.textContent = `${question.id}：${winner ? winner.group_name + " — " + winner.answers.map(answer => answer.answer).join(" / ") : "無得主"}`;
    board.append(row);
  }
  const scores = document.querySelector("#projector-leaderboard");
  if (scores) scores.textContent = (result.scores || []).map(score => `${score.group_name}：${score.wins} 題`).join("\n");
}

function showProjectionCountdown() {
  const display = document.querySelector("#projector-countdown");
  if (!display) return;
  let count = 3;
  display.classList.remove("countdown-pulse");
  const tick = () => {
    display.textContent = count > 0 ? String(count) : "搶答開始！";
    display.classList.remove("countdown-pulse"); void display.offsetWidth; display.classList.add("countdown-pulse");
    count -= 1;
    if (count >= 0) setTimeout(tick, 700);
  };
  tick();
}

document.querySelector("#answer-board")?.addEventListener("click", async event => {
  const button = event.target.closest(".submit-bundle");
  if (!button || button.disabled) return;
  const room = window.quizRoom;
  const card = button.closest(".question-card");
  const inputs = [...card.querySelectorAll("input[data-slot-id]")];
  if (inputs.some(input => !input.value.trim())) { document.querySelector("#student-message").textContent = "請填寫所有空格。"; return; }
  button.disabled = true;
  try {
    await api(`/api/rooms/${encodeURIComponent(room.roomId)}/submissions`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({group_id: room.groupId, group_token: room.token, bundle_id: button.dataset.bundleId, answers: Object.fromEntries(inputs.map(input => [input.dataset.slotId, input.value]))})});
    card.querySelectorAll("input").forEach(input => { input.disabled = true; });
    button.textContent = "已送出";
    document.querySelector("#student-message").textContent = "已送出答案。";
  } catch (error) { button.disabled = room.status !== "active"; document.querySelector("#student-message").textContent = error.message; }
});

function connectRoom(role, identity) {
  if (window.quizSocket && window.quizSocket.readyState < WebSocket.CLOSING) window.quizSocket.close();
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws/${encodeURIComponent(identity.roomId)}`);
  window.quizSocket = socket;
  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({role, token: identity.token, group_id: identity.groupId}));
    if (window.quizPingTimer) clearInterval(window.quizPingTimer);
    window.quizPingTimer = setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type: "ping"}));
    }, 20000);
  });
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.type === "snapshot") {
      if (role === "teacher") {
        setTeacherPhase(message.status);
        if (message.groups) renderGroups(message.groups);
        if (message.progress) renderTeacherProgress(message.progress);
        if (message.results) showResults(message.results);
      } else if (role === "student") {
        setStudentPhase(message.status);
        for (const card of document.querySelectorAll(".question-card")) {
          if ((message.submitted_bundles || []).includes(card.dataset.bundleId)) {
            card.querySelectorAll("input, button").forEach(control => { control.disabled = true; });
            const status = document.createElement("p"); status.textContent = "已送出"; card.append(status);
          }
        }
        if (message.status === "ended" && message.results) showResults(message.results);
      } else if (role === "projection") {
        if (message.results) showResults(message.results);
        if (message.status === "active") document.querySelector("#projector-countdown").textContent = "搶答進行中";
        else if (message.status === "ended") document.querySelector("#projector-countdown").textContent = "搶答結束";
      }
    } else if (message.type === "phase.changed") {
      if (role === "teacher") setTeacherPhase(message.status);
      if (role === "student") setStudentPhase(message.status);
      if (role === "projection") {
        if (message.status === "active") showProjectionCountdown();
        else if (message.status === "ended") document.querySelector("#projector-countdown").textContent = "搶答結束";
      }
    } else if (message.type === "groups.updated" && role === "teacher") {
      renderGroups(message.groups);
    } else if (message.type === "progress.updated" && role === "teacher") {
      renderTeacherProgress(message.progress);
    } else if (message.type === "results.updated" && (role !== "student" || window.quizRoom?.status === "ended")) {
      showResults(message);
    }
  });
  socket.addEventListener("close", () => {
    if (window.quizPingTimer) clearInterval(window.quizPingTimer);
    if (window.quizSocket !== socket) return;
    if (document.visibilityState !== "hidden") {
      window.quizReconnectTimer = setTimeout(() => {
        if (sessionStorage.getItem(role === "teacher" ? "quiz-teacher" : "quiz-group")) connectRoom(role, identity);
      }, 2500);
    }
  });
}

function renderGroups(groups) {
  const list = $("#group-list");
  if (!list) return;
  list.replaceChildren();
  if (!groups.length) {
    const empty = document.createElement("li");
    empty.textContent = "尚無組別";
    list.append(empty);
    return;
  }
  for (const group of groups) {
    const item = document.createElement("li");
    item.textContent = group.name;
    list.append(item);
  }
}

function initProjector() {
  if (document.body.dataset.page !== "projector") return;
  const parts = location.pathname.split("/").filter(Boolean);
  const roomId = parts[1];
  const token = location.hash.slice(1);
  if (roomId) connectRoom("projection", {roomId, token});
}

initTeacher();
initStudent();
initProjector();
