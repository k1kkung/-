(function () {
  "use strict";

  var ANSWER_LABELS = {
    yes: "是",
    no: "不是",
    irrelevant: "与此无关",
  };

  var AI_STATUS_LABELS = {
    loading: "正在加载本地模型",
    ready: "本地 AI",
    rules: "规则模式",
  };

  var DATA = window.SOUP_DATA || {
    genres: [],
    difficulties: [],
    scales: [],
    stories: [],
  };

  var DEFAULT_PREFERENCES = {
    genres: [],
    difficulties: [],
    scales: [],
    ai_hint: true,
  };

  var state = {
    preferences: {
      genres: [],
      difficulties: [],
      scales: [],
      ai_hint: true,
    },
    catalog: null,
    mode: "draw",
    preview: null,
    currentStory: null,
    questionCount: 0,
    hintsUsed: 0,
    revealed: false,
    judging: false,
    browsePage: 1,
    browseQuery: "",
  };

  var bridgeState = {
    checked: false,
    available: false,
  };

  var refs = {};

  function createElement(tagName, className, text) {
    var element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    if (typeof text === "string") {
      element.textContent = text;
    }
    return element;
  }

  function normalizeText(value) {
    return String(value || "")
      .normalize("NFKC")
      .toLowerCase()
      .replace(/是不是/g, "是否")
      .replace(/有没有/g, "是否")
      .replace(/会不会/g, "是否")
      .replace(/能不能/g, "是否")
      .replace(/可不可以/g, "是否")
      .replace(/瞎子|失明/g, "盲人")
      .replace(/看不见/g, "视障")
      .replace(/断电|没电/g, "停电")
      .replace(/维修工|维修人员|电工/g, "维修员")
      .replace(
        /[\s，。！？、,.!?;；:："'“”‘’（）()【】\[\]《》<>—–-]/g,
        ""
      );
  }

  function containsTerm(text, term) {
    var normalizedTerm = normalizeText(term);
    return normalizedTerm.length > 0 && text.indexOf(normalizedTerm) >= 0;
  }

  function hasNegation(text) {
    return /(没有|没|不是|并非|未|不会|不可能|未曾)/.test(text);
  }

  function localJudge(storyId, question) {
    var story = getLocalStory(storyId);
    if (!story || !Array.isArray(story.facts)) {
      return "irrelevant";
    }

    var normalizedQuestion = normalizeText(question);
    if (!normalizedQuestion) {
      return "irrelevant";
    }

    var best = null;
    story.facts.forEach(function (fact) {
      var score = 0;
      (fact.aliases || []).forEach(function (alias) {
        var candidate = normalizeText(alias);
        if (!candidate) {
          return;
        }
        if (
          normalizedQuestion.indexOf(candidate) >= 0 ||
          (candidate.length >= 4 &&
            candidate.indexOf(normalizedQuestion) >= 0)
        ) {
          score = Math.max(score, candidate.length);
        }
      });
      var description = normalizeText(fact.description);
      if (
        description &&
        (normalizedQuestion.indexOf(description) >= 0 ||
          (description.length >= 4 &&
            description.indexOf(normalizedQuestion) >= 0))
      ) {
        score = Math.max(score, description.length);
      }
      if (!best || score > best.score) {
        best = { score: score, fact: fact };
      }
    });

    if (!best || best.score < 2) {
      return "irrelevant";
    }

    if (hasNegation(normalizedQuestion)) {
      return best.fact.truth ? "no" : "yes";
    }
    return best.fact.truth ? "yes" : "no";
  }

  function getLocalStories() {
    return DATA.stories || window.STORIES || [];
  }

  function getLocalStory(storyId) {
    return (
      getLocalStories().find(function (story) {
        return story.id === storyId;
      }) || null
    );
  }

  function readStorage(key, fallbackValue) {
    try {
      var value = window.localStorage.getItem(key);
      return value ? JSON.parse(value) : fallbackValue;
    } catch (error) {
      return fallbackValue;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      return;
    }
  }

  function getLocalPreferences() {
    var saved = readStorage("soup.ai.preferences", DEFAULT_PREFERENCES);
    return {
      genres: Array.isArray(saved.genres) ? saved.genres : [],
      difficulties: Array.isArray(saved.difficulties)
        ? saved.difficulties
        : [],
      scales: Array.isArray(saved.scales) ? saved.scales : [],
      ai_hint: saved.ai_hint !== false,
    };
  }

  function saveLocalPreferences(preferences) {
    writeStorage("soup.ai.preferences", preferences);
    return true;
  }

  function getLocalSeen() {
    return readStorage("soup.ai.seen", {});
  }

  function getLocalDisliked() {
    return readStorage("soup.ai.disliked", []);
  }

  function setLocalSeen(seen) {
    writeStorage("soup.ai.seen", seen);
  }

  function setLocalDisliked(disliked) {
    writeStorage("soup.ai.disliked", disliked);
  }

  function filterLocalStories(preferences, query, excludeDisliked) {
    var disliked = getLocalDisliked();
    var normalizedQuery = normalizeText(query);
    var genreFilter = (preferences && preferences.genres) || [];
    var difficultyFilter =
      (preferences && preferences.difficulties) || [];
    var scaleFilter = (preferences && preferences.scales) || [];

    return getLocalStories().filter(function (story) {
      if (excludeDisliked && disliked.indexOf(story.id) >= 0) {
        return false;
      }
      var storyGenres =
        story.genres && story.genres.length
          ? story.genres
          : [story.primary_genre].concat(story.secondary_genres || []);
      if (
        genreFilter.length &&
        !genreFilter.some(function (genre) {
          return storyGenres.indexOf(genre) >= 0;
        })
      ) {
        return false;
      }
      if (
        difficultyFilter.length &&
        difficultyFilter.indexOf(story.difficulty) < 0
      ) {
        return false;
      }
      if (
        scaleFilter.length &&
        scaleFilter.indexOf(story.scale) < 0
      ) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      var searchText = normalizeText(
        [
          story.title,
          story.surface,
          (story.tags || []).join(""),
          storyGenres.join(""),
        ].join("")
      );
      return searchText.indexOf(normalizedQuery) >= 0;
    });
  }

  function localCatalog() {
    return {
      genres: DATA.genres || [],
      difficulties: DATA.difficulties || [],
      scales: DATA.scales || [],
      story_count: getLocalStories().length,
      disliked_count: getLocalDisliked().length,
    };
  }

  function localSearch(query, preferences, page, pageSize) {
    var stories = filterLocalStories(preferences, query, false);
    var disliked = getLocalDisliked();
    var seen = getLocalSeen();
    var size = Math.max(1, Math.min(Number(pageSize) || 12, 60));
    var currentPage = Math.max(1, Number(page) || 1);
    var total = stories.length;
    var startIndex = (currentPage - 1) * size;
    var items = stories.slice(startIndex, startIndex + size).map(
      function (story) {
        var copy = Object.assign({}, story);
        copy.seen_count = seen[story.id] || 0;
        copy.is_disliked = disliked.indexOf(story.id) >= 0;
        return copy;
      }
    );
    return {
      items: items,
      page: currentPage,
      page_size: size,
      total: total,
      page_count: Math.max(1, Math.ceil(total / size)),
    };
  }

  function localDraw(preferences) {
    var candidates = filterLocalStories(preferences, "", true);
    if (!candidates.length) {
      return null;
    }
    var seen = getLocalSeen();
    var minimumSeen = candidates.reduce(function (minimum, story) {
      return Math.min(minimum, seen[story.id] || 0);
    }, Infinity);
    var pool = candidates.filter(function (story) {
      return (seen[story.id] || 0) === minimumSeen;
    });
    var story = pool[Math.floor(Math.random() * pool.length)];
    seen[story.id] = (seen[story.id] || 0) + 1;
    setLocalSeen(seen);
    var copy = Object.assign({}, story);
    copy.seen_count = seen[story.id];
    copy.is_disliked = false;
    return copy;
  }

  function localReveal(storyId) {
    var story = getLocalStory(storyId);
    if (!story) {
      return null;
    }
    return {
      id: story.id,
      title: story.title,
      bottom: story.bottom,
      facts: (story.facts || []).map(function (fact) {
        return {
          description: fact.description,
          truth: fact.truth,
        };
      }),
    };
  }

  function localHint(storyId, hintsUsed, useAi) {
    var story = getLocalStory(storyId);
    if (!story || !Array.isArray(story.hints)) {
      return null;
    }
    var index = Math.max(0, Number(hintsUsed) || 0);
    if (index >= story.hints.length || index >= 2) {
      return null;
    }
    return {
      hint: story.hints[index],
      hint_index: index,
      used: index + 1,
      max: 2,
      source: "static",
    };
  }

  function localMarkDisliked(storyId) {
    var disliked = getLocalDisliked();
    if (disliked.indexOf(storyId) < 0) {
      disliked.push(storyId);
      setLocalDisliked(disliked);
    }
    return true;
  }

  function localClearPreferences() {
    try {
      window.localStorage.removeItem("soup.ai.preferences");
      window.localStorage.removeItem("soup.ai.seen");
      window.localStorage.removeItem("soup.ai.disliked");
    } catch (error) {
      return;
    }
  }

  function getPywebviewApi() {
    if (!window.pywebview || !window.pywebview.api) {
      return null;
    }
    return window.pywebview.api;
  }

  function waitForPywebviewApi(timeoutMs) {
    return new Promise(function (resolve) {
      var startedAt = Date.now();

      function check() {
        var api = getPywebviewApi();
        if (api) {
          resolve(api);
          return;
        }
        if (Date.now() - startedAt >= timeoutMs) {
          resolve(null);
          return;
        }
        window.setTimeout(check, 100);
      }

      check();
    });
  }

  function withTimeout(promise, timeoutMs) {
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timer = window.setTimeout(function () {
        if (!settled) {
          settled = true;
          reject(new Error("timeout"));
        }
      }, timeoutMs);

      Promise.resolve(promise).then(
        function (value) {
          if (!settled) {
            settled = true;
            window.clearTimeout(timer);
            resolve(value);
          }
        },
        function (error) {
          if (!settled) {
            settled = true;
            window.clearTimeout(timer);
            reject(error);
          }
        }
      );
    });
  }

  function dataCall(method, args, fallback, timeoutMs) {
    var fallbackFunction =
      fallback ||
      function () {
        return null;
      };

    return waitForPywebviewApi(1500).then(function (api) {
      if (!api || typeof api[method] !== "function") {
        bridgeState.checked = true;
        bridgeState.available = false;
        return fallbackFunction();
      }

      bridgeState.checked = true;
      bridgeState.available = true;
      return withTimeout(
        Promise.resolve().then(function () {
          return api[method].apply(api, args);
        }),
        timeoutMs || 8000
      ).catch(function () {
        return fallbackFunction();
      });
    });
  }

  function setAiStatus(statusName) {
    if (!refs.aiStatus) {
      return;
    }
    refs.aiStatus.textContent =
      AI_STATUS_LABELS[statusName] || AI_STATUS_LABELS.rules;
    refs.aiStatus.dataset.aiStatus = statusName;
  }

  function refreshAiStatus() {
    setAiStatus("loading");
    return dataCall(
      "get_ai_status",
      [],
      function () {
        return "rules";
      },
      3000
    ).then(function (status) {
      setAiStatus(status === "ready" ? "ready" : "rules");
      return status;
    });
  }

  function cacheElements() {
    refs.libraryView = document.getElementById("libraryView");
    refs.gameView = document.getElementById("gameView");
    refs.drawTab = document.getElementById("drawTab");
    refs.browseTab = document.getElementById("browseTab");
    refs.configPanel = document.getElementById("configPanel");
    refs.genreFilters = document.getElementById("genreFilters");
    refs.difficultyFilters = document.getElementById("difficultyFilters");
    refs.scaleFilters = document.getElementById("scaleFilters");
    refs.aiHintToggle = document.getElementById("aiHintToggle");
    refs.aiStatus = document.getElementById("aiStatus");
    refs.clearPreferencesButton = document.getElementById(
      "clearPreferencesButton"
    );
    refs.drawButton = document.getElementById("drawButton");
    refs.configStatus = document.getElementById("configStatus");
    refs.previewPanel = document.getElementById("previewPanel");
    refs.previewMeta = document.getElementById("previewMeta");
    refs.previewTitle = document.getElementById("previewTitle");
    refs.previewSurface = document.getElementById("previewSurface");
    refs.previewWarning = document.getElementById("previewWarning");
    refs.previewSwitchButton = document.getElementById(
      "previewSwitchButton"
    );
    refs.previewDislikeButton = document.getElementById(
      "previewDislikeButton"
    );
    refs.previewStartButton = document.getElementById(
      "previewStartButton"
    );
    refs.browsePanel = document.getElementById("browsePanel");
    refs.browseSearch = document.getElementById("browseSearch");
    refs.browseCount = document.getElementById("browseCount");
    refs.storyGrid = document.getElementById("storyGrid");
    refs.browsePrevButton = document.getElementById("browsePrevButton");
    refs.browseNextButton = document.getElementById("browseNextButton");
    refs.browsePageLabel = document.getElementById("browsePageLabel");
    refs.brandButton = document.getElementById("brandButton");
    refs.backToLibraryButton = document.getElementById("backToLibraryButton");
    refs.gameGenre = document.getElementById("gameGenre");
    refs.gameTitle = document.getElementById("gameTitle");
    refs.gameScale = document.getElementById("gameScale");
    refs.questionCount = document.getElementById("questionCount");
    refs.hintCount = document.getElementById("hintCount");
    refs.storyMeta = document.getElementById("storyMeta");
    refs.storySurface = document.getElementById("storySurface");
    refs.suggestionBox = document.getElementById("suggestionBox");
    refs.suggestionList = document.getElementById("suggestionList");
    refs.hintBox = document.getElementById("hintBox");
    refs.hintText = document.getElementById("hintText");
    refs.chatLog = document.getElementById("chatLog");
    refs.questionForm = document.getElementById("questionForm");
    refs.questionInput = document.getElementById("questionInput");
    refs.sendButton = document.getElementById("sendButton");
    refs.hintButton = document.getElementById("hintButton");
    refs.revealButton = document.getElementById("revealButton");
    refs.restartButton = document.getElementById("restartButton");
    refs.switchStoryButton = document.getElementById("switchStoryButton");
    refs.dislikeStoryButton = document.getElementById(
      "dislikeStoryButton"
    );
    refs.resultDialog = document.getElementById("resultDialog");
    refs.resultTitle = document.getElementById("resultTitle");
    refs.resultBottom = document.getElementById("resultBottom");
    refs.resultFacts = document.getElementById("resultFacts");
    refs.resultQuestions = document.getElementById("resultQuestions");
    refs.resultHints = document.getElementById("resultHints");
    refs.resultCloseButton = document.getElementById("resultCloseButton");
    refs.resultRestartButton = document.getElementById(
      "resultRestartButton"
    );
  }

  function renderFilterGroup(container, values, key) {
    container.textContent = "";
    values.forEach(function (value) {
      var button = createElement("button", "filter-option", value);
      var selected = state.preferences[key].indexOf(value) >= 0;
      if (selected) {
        button.classList.add("filter-option--active");
      }
      button.type = "button";
      button.addEventListener("click", function () {
        var current = state.preferences[key];
        var index = current.indexOf(value);
        if (index >= 0) {
          current.splice(index, 1);
        } else {
          current.push(value);
        }
        savePreferences();
        renderFilters();
        if (state.mode === "browse") {
          renderBrowse();
        }
      });
      container.appendChild(button);
    });
  }

  function renderFilters() {
    renderFilterGroup(
      refs.genreFilters,
      (state.catalog && state.catalog.genres) || DATA.genres || [],
      "genres"
    );
    renderFilterGroup(
      refs.difficultyFilters,
      (state.catalog && state.catalog.difficulties) ||
        DATA.difficulties ||
        [],
      "difficulties"
    );
    renderFilterGroup(
      refs.scaleFilters,
      (state.catalog && state.catalog.scales) || DATA.scales || [],
      "scales"
    );
    refs.aiHintToggle.checked = state.preferences.ai_hint !== false;
  }

  function savePreferences() {
    return dataCall(
      "save_preferences",
      [state.preferences],
      function () {
        saveLocalPreferences(state.preferences);
        return true;
      },
      5000
    );
  }

  function applyPreferences(preferences) {
    state.preferences = {
      genres: (preferences && preferences.genres) || [],
      difficulties: (preferences && preferences.difficulties) || [],
      scales: (preferences && preferences.scales) || [],
      ai_hint: !preferences || preferences.ai_hint !== false,
    };
    renderFilters();
  }

  function setLibraryMode(mode) {
    state.mode = mode;
    var drawMode = mode === "draw";
    refs.drawTab.classList.toggle("mode-tab--active", drawMode);
    refs.browseTab.classList.toggle("mode-tab--active", !drawMode);
    refs.drawTab.setAttribute("aria-selected", drawMode ? "true" : "false");
    refs.browseTab.setAttribute(
      "aria-selected",
      drawMode ? "false" : "true"
    );
    refs.configPanel.hidden = false;
    refs.previewPanel.hidden = !drawMode || !state.preview;
    refs.browsePanel.hidden = drawMode;
    if (!drawMode) {
      renderBrowse();
    }
  }

  function setConfigStatus(message, isError) {
    refs.configStatus.textContent = message || "";
    refs.configStatus.hidden = !message;
    refs.configStatus.classList.toggle("config-status--error", !!isError);
  }

  function createMetaChip(text) {
    return createElement("span", "meta-chip", text);
  }

  function renderPreview(story) {
    state.preview = story;
    refs.previewMeta.textContent = "";
    [
      story.primary_genre,
      story.difficulty,
      story.scale,
      "已抽到",
    ].forEach(function (value) {
      refs.previewMeta.appendChild(createMetaChip(value));
    });
    refs.previewTitle.textContent = story.title;
    refs.previewSurface.textContent = story.surface;
    if (story.warnings && story.warnings.length) {
      refs.previewWarning.textContent = "内容提示：" + story.warnings.join("；");
      refs.previewWarning.hidden = false;
    } else {
      refs.previewWarning.hidden = true;
    }
    refs.previewPanel.hidden = false;
  }

  function renderStoryMeta(story) {
    refs.gameGenre.textContent = story.primary_genre || "";
    refs.gameTitle.textContent = story.title;
    refs.gameScale.textContent = story.scale || "";
    refs.storySurface.textContent = story.surface;
    refs.storyMeta.textContent = "";
    [
      story.primary_genre,
      story.difficulty,
      story.scale,
      "可提示 2 次",
    ].forEach(function (value) {
      refs.storyMeta.appendChild(createMetaChip(value));
    });
  }

  function renderSuggestions(story) {
    var suggestions = story.suggestions || [];
    refs.suggestionBox.hidden = suggestions.length === 0;
    refs.suggestionList.textContent = "";
    suggestions.forEach(function (suggestion) {
      var button = createElement(
        "button",
        "suggestion-button",
        suggestion
      );
      button.type = "button";
      button.addEventListener("click", function () {
        submitQuestion(suggestion);
      });
      refs.suggestionList.appendChild(button);
    });
  }

  function updateStats() {
    var maxHints = state.currentStory ? 2 : 2;
    refs.questionCount.textContent = String(state.questionCount);
    refs.hintCount.textContent = String(
      Math.max(0, maxHints - state.hintsUsed)
    );
  }

  function updateControls() {
    var gameReady =
      Boolean(state.currentStory) && !state.revealed && !state.judging;
    var question = refs.questionInput.value.trim();
    refs.questionInput.disabled = !gameReady;
    refs.sendButton.disabled = !gameReady || !question;
    refs.hintButton.disabled =
      !gameReady || state.hintsUsed >= 2;
    refs.revealButton.disabled = !gameReady;
    refs.restartButton.disabled = !state.currentStory || state.judging;
    refs.switchStoryButton.disabled = state.judging;
    refs.dislikeStoryButton.disabled = !state.currentStory && !state.preview;
    refs.suggestionList
      .querySelectorAll(".suggestion-button")
      .forEach(function (button) {
        button.disabled = !gameReady;
      });
  }

  function clearComposer() {
    refs.questionInput.value = "";
    refs.questionInput.style.height = "";
    updateControls();
  }

  function scrollChatToBottom() {
    window.requestAnimationFrame(function () {
      refs.chatLog.scrollTop = refs.chatLog.scrollHeight;
    });
  }

  function appendMessage(role, text, answer) {
    var message = createElement("div", "message message--" + role);
    var messageLabels = {
      user: "你",
      hint: "提示",
      ai: "裁判",
      system: "开始",
    };
    message.appendChild(
      createElement(
        "div",
        "message__meta",
        messageLabels[role] || ""
      )
    );

    if (role === "ai" && answer) {
      message.appendChild(
        createElement(
          "span",
          "answer-chip answer-chip--" + answer,
          ANSWER_LABELS[answer]
        )
      );
    } else {
      message.appendChild(
        createElement("div", "message__bubble", text || "")
      );
    }
    refs.chatLog.appendChild(message);
    scrollChatToBottom();
  }

  function setView(viewName) {
    var showLibrary = viewName === "library";
    refs.libraryView.hidden = !showLibrary;
    refs.gameView.hidden = showLibrary;
  }

  function drawStory(autoStart) {
    setConfigStatus("");
    return dataCall(
      "draw_story",
      [state.preferences],
      function () {
        return localDraw(state.preferences);
      },
      10000
    ).then(function (story) {
      if (!story) {
        setConfigStatus(
          "当前条件没有可用故事，请放宽题材、难度或尺度。",
          true
        );
        return null;
      }
      state.preview = story;
      if (autoStart) {
        return startStory(story.id);
      }
      renderPreview(story);
      setLibraryMode("draw");
      return story;
    });
  }

  function startStory(storyId) {
    return dataCall(
      "get_story",
      [storyId],
      function () {
        return getLocalStory(storyId);
      },
      5000
    ).then(function (story) {
      if (!story) {
        return null;
      }
      state.currentStory = story;
      state.preview = story;
      state.questionCount = 0;
      state.hintsUsed = 0;
      state.revealed = false;
      state.judging = false;
      refs.chatLog.textContent = "";
      refs.hintBox.hidden = true;
      refs.hintText.textContent = "";
      renderStoryMeta(story);
      renderSuggestions(story);
      updateStats();
      setView("game");
      appendMessage("system", "汤面已公布，裁判开始回答。");
      clearComposer();
      updateControls();
      return story;
    });
  }

  function switchStory() {
    state.preview = null;
    return drawStory(true);
  }

  function dislikeStory() {
    var story = state.currentStory || state.preview;
    if (!story) {
      return;
    }
    return dataCall(
      "mark_disliked",
      [story.id],
      function () {
        return localMarkDisliked(story.id);
      },
      5000
    ).then(function () {
      state.preview = null;
      setConfigStatus("已记录，这道题不会再被推荐。");
      if (state.currentStory) {
        state.currentStory = null;
        setView("library");
        return drawStory(true);
      }
      return drawStory(false);
    });
  }

  function renderBrowse() {
    var query = refs.browseSearch.value.trim();
    state.browseQuery = query;
    return dataCall(
      "search_stories",
      [query, state.preferences, state.browsePage, 12],
      function () {
        return localSearch(
          query,
          state.preferences,
          state.browsePage,
          12
        );
      },
      8000
    ).then(function (result) {
      state.browsePage = result.page || 1;
      refs.storyGrid.textContent = "";
      refs.browseCount.textContent =
        "共 " + result.total + " 条 · 第 " + result.page + " 页";
      refs.browsePageLabel.textContent =
        "第 " + result.page + " / " + result.page_count + " 页";
      refs.browsePrevButton.disabled = result.page <= 1;
      refs.browseNextButton.disabled = result.page >= result.page_count;

      result.items.forEach(function (story) {
        var card = createElement("article", "story-card story-card--compact");
        card.dataset.storyId = story.id;
        var top = createElement("div", "story-card__top");
        top.append(
          createElement("span", "tag tag--genre", story.primary_genre),
          createElement(
            "span",
            "tag tag--difficulty",
            story.difficulty + " · " + story.scale
          )
        );
        card.appendChild(top);
        card.appendChild(
          createElement("strong", "story-card__title", story.title)
        );
        card.appendChild(
          createElement(
            "span",
            "story-card__surface",
            story.surface
          )
        );
        var footer = createElement("div", "story-card__footer");
        footer.appendChild(
          createElement(
            "span",
            "story-card__time",
            story.is_disliked ? "已不再推荐" : "题库故事"
          )
        );
        var startButton = createElement(
          "button",
          "action-button action-button--emphasis",
          "开始推理"
        );
        startButton.type = "button";
        startButton.addEventListener("click", function () {
          startStory(story.id);
        });
        footer.appendChild(startButton);
        card.appendChild(footer);
        refs.storyGrid.appendChild(card);
      });
    });
  }

  function submitQuestion(questionText) {
    if (!state.currentStory || state.revealed || state.judging) {
      return;
    }
    var question = String(questionText || refs.questionInput.value).trim();
    if (!question) {
      return;
    }

    var storyId = state.currentStory.id;
    var localAnswer = localJudge(storyId, question);
    appendMessage("user", question);
    state.questionCount += 1;
    state.judging = true;
    updateStats();
    updateControls();

    dataCall(
      "judge",
      [storyId, question],
      function () {
        return localAnswer;
      },
      32000
    )
      .then(function (answer) {
        if (
          answer !== "yes" &&
          answer !== "no" &&
          answer !== "irrelevant"
        ) {
          answer = localAnswer;
        }
        appendMessage("ai", "", answer);
        state.judging = false;
        clearComposer();
        updateControls();
      })
      .catch(function () {
        appendMessage("ai", "", localAnswer);
        state.judging = false;
        clearComposer();
        updateControls();
      });
  }

  function useHint() {
    if (!state.currentStory || state.revealed || state.hintsUsed >= 2) {
      return;
    }
    dataCall(
      "get_hint",
      [state.currentStory.id, state.hintsUsed, state.preferences.ai_hint],
      function () {
        return localHint(
          state.currentStory.id,
          state.hintsUsed,
          state.preferences.ai_hint
        );
      },
      12000
    ).then(function (result) {
      if (!result || !result.hint) {
        setConfigStatus("没有更多可用提示。", true);
        return;
      }
      state.hintsUsed = result.used || state.hintsUsed + 1;
      refs.hintBox.hidden = false;
      refs.hintText.textContent = result.hint;
      appendMessage("hint", result.hint);
      updateStats();
      updateControls();
    });
  }

  function revealStory() {
    if (!state.currentStory || state.revealed) {
      return;
    }
    dataCall(
      "get_reveal",
      [state.currentStory.id],
      function () {
        return localReveal(state.currentStory.id);
      },
      5000
    ).then(function (reveal) {
      if (!reveal) {
        return;
      }
      state.revealed = true;
      refs.resultTitle.textContent = reveal.title;
      refs.resultBottom.textContent = reveal.bottom;
      refs.resultQuestions.textContent = String(state.questionCount);
      refs.resultHints.textContent = String(state.hintsUsed);
      refs.resultFacts.textContent = "";
      (reveal.facts || []).forEach(function (fact) {
        refs.resultFacts.appendChild(
          createElement("li", "", fact.description)
        );
      });
      if (typeof refs.resultDialog.showModal === "function") {
        refs.resultDialog.showModal();
      } else {
        refs.resultDialog.setAttribute("open", "");
      }
      updateControls();
    });
  }

  function showLibrary() {
    state.currentStory = null;
    state.questionCount = 0;
    state.hintsUsed = 0;
    state.revealed = false;
    state.judging = false;
    setView("library");
    setLibraryMode(state.mode);
    updateControls();
  }

  function clearPreferences() {
    return dataCall(
      "clear_preferences",
      [],
      function () {
        localClearPreferences();
        return true;
      },
      5000
    ).then(function () {
      state.preferences = Object.assign({}, DEFAULT_PREFERENCES, {
        genres: [],
        difficulties: [],
        scales: [],
      });
      renderFilters();
      setConfigStatus("筛选偏好和不再推荐记录已清空。");
      if (state.mode === "browse") {
        renderBrowse();
      }
    });
  }

  function bindEvents() {
    refs.drawTab.addEventListener("click", function () {
      setLibraryMode("draw");
    });
    refs.browseTab.addEventListener("click", function () {
      state.browsePage = 1;
      setLibraryMode("browse");
    });
    refs.drawButton.addEventListener("click", function () {
      drawStory(false);
    });
    refs.clearPreferencesButton.addEventListener("click", clearPreferences);
    refs.aiHintToggle.addEventListener("change", function () {
      state.preferences.ai_hint = refs.aiHintToggle.checked;
      savePreferences();
    });
    refs.previewStartButton.addEventListener("click", function () {
      if (state.preview) {
        startStory(state.preview.id);
      }
    });
    refs.previewSwitchButton.addEventListener("click", function () {
      state.preview = null;
      drawStory(false);
    });
    refs.previewDislikeButton.addEventListener("click", dislikeStory);
    refs.switchStoryButton.addEventListener("click", switchStory);
    refs.dislikeStoryButton.addEventListener("click", dislikeStory);
    refs.browseSearch.addEventListener("input", function () {
      state.browsePage = 1;
      window.clearTimeout(refs.browseSearch._timer);
      refs.browseSearch._timer = window.setTimeout(renderBrowse, 180);
    });
    refs.browsePrevButton.addEventListener("click", function () {
      state.browsePage -= 1;
      renderBrowse();
    });
    refs.browseNextButton.addEventListener("click", function () {
      state.browsePage += 1;
      renderBrowse();
    });
    refs.brandButton.addEventListener("click", showLibrary);
    refs.backToLibraryButton.addEventListener("click", showLibrary);
    refs.restartButton.addEventListener("click", showLibrary);
    refs.hintButton.addEventListener("click", useHint);
    refs.revealButton.addEventListener("click", revealStory);
    refs.questionForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitQuestion();
    });
    refs.questionInput.addEventListener("input", function () {
      updateControls();
    });
    refs.questionInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        refs.questionForm.requestSubmit();
      }
    });
    refs.resultCloseButton.addEventListener("click", function () {
      refs.resultDialog.close();
    });
    refs.resultRestartButton.addEventListener("click", function () {
      refs.resultDialog.close();
      showLibrary();
    });
    window.addEventListener("pywebviewready", function () {
      bridgeState.checked = false;
      refreshAiStatus();
      dataCall(
        "get_preferences",
        [],
        getLocalPreferences,
        5000
      ).then(applyPreferences);
    });
  }

  function openStoryFromLocation() {
    if (typeof window.location === "undefined") {
      return;
    }
    var storyId = new URLSearchParams(window.location.search).get("story");
    if (storyId && getLocalStory(storyId)) {
      startStory(storyId);
    }
  }

  function init() {
    cacheElements();
    renderFilters();
    bindEvents();
    setView("library");
    setLibraryMode("draw");
    updateStats();
    updateControls();
    refreshAiStatus();
    setAiStatus("loading");

    dataCall(
      "get_preferences",
      [],
      getLocalPreferences,
      5000
    ).then(applyPreferences);
    dataCall(
      "get_catalog",
      [],
      localCatalog,
      5000
    ).then(function (catalog) {
      state.catalog = catalog;
      renderFilters();
    });
    openStoryFromLocation();
  }

  window.HaiTangEngine = {
    normalizeText: normalizeText,
    localJudge: localJudge,
    localSearch: localSearch,
    localDraw: localDraw,
    localCatalog: localCatalog,
    localHint: localHint,
  };

  if (typeof document === "undefined") {
    return;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
