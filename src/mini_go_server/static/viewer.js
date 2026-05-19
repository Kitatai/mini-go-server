const state = { eventCount: 0, board: "" };
    const ids = {
      connection: document.getElementById("connection"),
      matchTitle: document.getElementById("matchTitle"),
      result: document.getElementById("result"),
      blackName: document.getElementById("blackName"),
      whiteName: document.getElementById("whiteName"),
      blackCard: document.getElementById("blackCard"),
      whiteCard: document.getElementById("whiteCard"),
      blackOpenBadge: document.getElementById("blackOpenBadge"),
      whiteOpenBadge: document.getElementById("whiteOpenBadge"),
      blackChooseBadge: document.getElementById("blackChooseBadge"),
      whiteChooseBadge: document.getElementById("whiteChooseBadge"),
      nextTurn: document.getElementById("nextTurn"),
      lastMove: document.getElementById("lastMove"),
      openPlayer: document.getElementById("openPlayer"),
      openingMove: document.getElementById("openingMove"),
      openingSummaryOpen: document.getElementById("openingSummaryOpen"),
      openingSummaryMove: document.getElementById("openingSummaryMove"),
      eventCount: document.getElementById("eventCount"),
      board: document.getElementById("board"),
      log: document.getElementById("log"),
    };

    function setConnection(text, connected) {
      ids.connection.classList.toggle("connected", connected);
      ids.connection.querySelector("span:last-child").textContent = text;
    }

    function renderBoard(text, lastMove) {
      if (!text) return;
      state.board = text;
      ids.board.innerHTML = "";
      fitBoard(text.length);
      [...text].forEach((cell, index) => {
        const point = document.createElement("div");
        point.className = "point";
        if (index === lastMove) point.classList.add("last");
        const stone = document.createElement("div");
        stone.className = "stone";
        if (cell === "X") stone.classList.add("black");
        if (cell === "O") stone.classList.add("white");
        if (cell === ".") stone.classList.add("empty");
        stone.textContent = cell === "." ? "" : cell;
        const label = document.createElement("div");
        label.className = "index";
        label.textContent = String(index);
        point.append(stone, label);
        ids.board.appendChild(point);
      });
    }

    function fitBoard(size) {
      const wrap = ids.board.parentElement;
      const available = Math.max(260, wrap.clientWidth);
      const naturalCell = 52;
      const minCell = 16;
      const cell = Math.max(minCell, Math.min(naturalCell, Math.floor(available / Math.max(1, size))));
      const stone = Math.max(12, Math.min(42, Math.floor(cell * 0.82)));
      const pointTop = Math.max(10, Math.floor(stone / 2));
      const boardHeight = Math.max(46, pointTop + stone + 24);
      ids.board.style.setProperty("--cell-size", `${cell}px`);
      ids.board.style.setProperty("--stone-size", `${stone}px`);
      ids.board.style.setProperty("--point-top", `${pointTop}px`);
      ids.board.style.setProperty("--board-height", `${boardHeight}px`);
    }

    window.addEventListener("resize", () => {
      if (state.board) renderBoard(state.board);
    });

    function appendLog(event) {
      ids.log.textContent += `[${event.sequence}] ${event.type} ${JSON.stringify(event)}\\n`;
      ids.log.scrollTop = ids.log.scrollHeight;
    }

    function renderOpenBadges() {
      const opener = ids.openPlayer.textContent;
      const blackName = ids.blackName.textContent;
      const whiteName = ids.whiteName.textContent;
      const chooser = state.chooser ?? "-";
      ids.blackOpenBadge.classList.toggle("visible", opener !== "-" && ids.blackName.textContent === opener);
      ids.whiteOpenBadge.classList.toggle("visible", opener !== "-" && ids.whiteName.textContent === opener);
      ids.blackChooseBadge.classList.toggle("visible", chooser !== "-" && blackName === chooser);
      ids.whiteChooseBadge.classList.toggle("visible", chooser !== "-" && whiteName === chooser);
      ids.openingSummaryOpen.textContent = opener;
      ids.openingSummaryMove.textContent = ids.openingMove.textContent;
    }

    function clearWinner() {
      ids.blackCard.classList.remove("winner");
      ids.whiteCard.classList.remove("winner");
    }

    function markWinner(winnerName) {
      clearWinner();
      if (ids.blackName.textContent === winnerName) ids.blackCard.classList.add("winner");
      if (ids.whiteName.textContent === winnerName) ids.whiteCard.classList.add("winner");
    }

    function applyEvent(event) {
      state.eventCount = event.sequence;
      if (event.match_id !== undefined) {
        state.matchId = event.match_id;
        ids.matchTitle.textContent = `match ${event.match_id}`;
      }
      if (event.black) ids.blackName.textContent = event.black;
      if (event.white) ids.whiteName.textContent = event.white;
      if (event.next_turn) ids.nextTurn.textContent = event.next_turn;
      if (event.move !== undefined) ids.lastMove.textContent = `${event.color ?? ""} ${event.move}`;
      if (event.board) renderBoard(event.board, event.move);
      if (event.type === "match_started") {
        clearWinner();
        ids.result.textContent = "対局中";
        state.chooser = event.chooser ?? "-";
        ids.openPlayer.textContent = event.opener ?? "-";
        ids.openingMove.textContent = "-";
        ids.openingSummaryOpen.textContent = event.opener ?? "-";
        ids.openingSummaryMove.textContent = "-";
        ids.nextTurn.textContent = "PIE_OPEN";
      }
      if (event.type === "opening_move") {
        ids.openPlayer.textContent = event.player ?? ids.openPlayer.textContent;
        ids.openingMove.textContent = `${event.move}`;
        ids.openingSummaryOpen.textContent = ids.openPlayer.textContent;
        ids.openingSummaryMove.textContent = `${event.move}`;
        ids.nextTurn.textContent = "PIE_CHOOSE";
      }
      if (event.type === "pie_selected") {
        ids.nextTurn.textContent = "WHITE";
      }
      if (event.type === "match_finished") {
        ids.result.textContent = `${event.winner_name} (${event.winner}) 勝ち`;
        ids.nextTurn.textContent = "GAME_OVER";
        markWinner(event.winner_name);
      }
      if (event.type === "match_forfeited") {
        ids.result.textContent = `${event.winner_name || "opponent"} 勝ち`;
        ids.nextTurn.textContent = "GAME_OVER";
        markWinner(event.winner_name);
      }
      ids.eventCount.textContent = String(state.eventCount);
      renderOpenBadges();
      appendLog(event);
    }

    const source = new EventSource("/events");
    source.onopen = () => setConnection("接続済み", true);
    source.onerror = () => setConnection("再接続中", false);
    ["server_started", "client_ready", "match_started", "opening_move", "pie_selected", "move_played", "match_finished", "match_forfeited"].forEach((name) => {
      source.addEventListener(name, (message) => applyEvent(JSON.parse(message.data)));
    });
