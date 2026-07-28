ObjC.import("Foundation");

function readRequest() {
  const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
  const text = ObjC.unwrap(
    $.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding)
  );
  return JSON.parse(text || "{}");
}

function toolError(code, message) {
  const error = new Error(message);
  error.toolCode = code;
  throw error;
}

function safeValue(read, fallback) {
  try {
    const value = read();
    return value === undefined || value === null ? fallback : value;
  } catch (_) {
    return fallback;
  }
}

function objectId(object) {
  return String(safeValue(function () { return object.id(); }, ""));
}

function objectName(object) {
  return String(safeValue(function () { return object.name(); }, ""));
}

function isoDate(value) {
  if (!value) return null;
  try {
    return value.toISOString();
  } catch (_) {
    try {
      return new Date(value).toISOString();
    } catch (_) {
      return null;
    }
  }
}

function accountRecord(account) {
  return {
    id: objectId(account),
    name: objectName(account),
    upgraded: Boolean(safeValue(function () { return account.upgraded(); }, false))
  };
}

function allAccounts(app) {
  return safeValue(function () { return app.accounts(); }, []);
}

function findAccount(app, selector, useDefault) {
  const accounts = allAccounts(app);
  if (selector) {
    const wanted = String(selector).toLocaleLowerCase();
    for (let index = 0; index < accounts.length; index += 1) {
      if (
        objectId(accounts[index]) === String(selector) ||
        objectName(accounts[index]).toLocaleLowerCase() === wanted
      ) {
        return accounts[index];
      }
    }
    toolError("ACCOUNT_NOT_FOUND", "Apple Notes account was not found: " + selector);
  }
  if (useDefault) {
    const defaultAccount = safeValue(function () { return app.defaultAccount(); }, null);
    if (defaultAccount && objectName(defaultAccount)) return defaultAccount;
  }
  return accounts.length ? accounts[0] : null;
}

function childFolders(container) {
  return safeValue(function () { return container.folders(); }, []);
}

function walkFolders(container, account, parentPath, parentId, output) {
  const folders = childFolders(container);
  for (let index = 0; index < folders.length; index += 1) {
    const folder = folders[index];
    const name = objectName(folder);
    const path = parentPath ? parentPath + "/" + name : name;
    output.push({
      folder: folder,
      record: {
        id: objectId(folder),
        name: name,
        path: path,
        parent_id: parentId || null,
        account_id: objectId(account),
        account_name: objectName(account)
      }
    });
    walkFolders(folder, account, path, objectId(folder), output);
  }
}

function folderEntries(account) {
  const output = [];
  walkFolders(account, account, "", null, output);
  return output;
}

function findFolder(account, selector, folderId, useDefault) {
  const entries = folderEntries(account);
  if (folderId) {
    for (let index = 0; index < entries.length; index += 1) {
      if (entries[index].record.id === String(folderId)) return entries[index];
    }
    toolError("FOLDER_NOT_FOUND", "Apple Notes folder ID was not found: " + folderId);
  }
  if (selector) {
    const wanted = String(selector).toLocaleLowerCase();
    const matches = entries.filter(function (entry) {
      return (
        entry.record.path.toLocaleLowerCase() === wanted ||
        entry.record.name.toLocaleLowerCase() === wanted
      );
    });
    if (matches.length === 1) return matches[0];
    if (matches.length > 1) {
      toolError(
        "AMBIGUOUS_FOLDER",
        "More than one folder is named " + selector + "; pass folder_id or a full folder path."
      );
    }
    toolError("FOLDER_NOT_FOUND", "Apple Notes folder was not found: " + selector);
  }
  if (useDefault) {
    const defaultFolder = safeValue(function () { return account.defaultFolder(); }, null);
    if (defaultFolder && objectName(defaultFolder)) {
      const defaultId = objectId(defaultFolder);
      for (let index = 0; index < entries.length; index += 1) {
        if (entries[index].record.id === defaultId) return entries[index];
      }
      return {
        folder: defaultFolder,
        record: {
          id: defaultId,
          name: objectName(defaultFolder),
          path: objectName(defaultFolder),
          parent_id: null,
          account_id: objectId(account),
          account_name: objectName(account)
        }
      };
    }
  }
  return entries.length ? entries[0] : null;
}

function directNotes(folder) {
  return safeValue(function () { return folder.notes(); }, []);
}

function noteRecord(note, account, folderRecord, includeBody) {
  const record = {
    id: objectId(note),
    name: objectName(note),
    account_id: account ? objectId(account) : null,
    account_name: account ? objectName(account) : null,
    folder_id: folderRecord ? folderRecord.id : null,
    folder_name: folderRecord ? folderRecord.name : null,
    folder_path: folderRecord ? folderRecord.path : null,
    created_at: isoDate(safeValue(function () { return note.creationDate(); }, null)),
    modified_at: isoDate(safeValue(function () { return note.modificationDate(); }, null)),
    password_protected: Boolean(
      safeValue(function () { return note.passwordProtected(); }, false)
    ),
    shared: Boolean(safeValue(function () { return note.shared(); }, false))
  };
  if (includeBody) {
    record.plaintext = String(safeValue(function () { return note.plaintext(); }, ""));
    record.body_html = String(safeValue(function () { return note.body(); }, ""));
  }
  return record;
}

function collectFolderNotes(entry, account, recursive, output, seen) {
  const notes = directNotes(entry.folder);
  for (let index = 0; index < notes.length; index += 1) {
    const id = objectId(notes[index]);
    if (!seen[id]) {
      seen[id] = true;
      output.push(noteRecord(notes[index], account, entry.record, false));
    }
  }
  if (!recursive) return;
  const prefix = entry.record.path + "/";
  const entries = folderEntries(account);
  for (let index = 0; index < entries.length; index += 1) {
    if (entries[index].record.path.indexOf(prefix) === 0) {
      const childNotes = directNotes(entries[index].folder);
      for (let noteIndex = 0; noteIndex < childNotes.length; noteIndex += 1) {
        const id = objectId(childNotes[noteIndex]);
        if (!seen[id]) {
          seen[id] = true;
          output.push(noteRecord(childNotes[noteIndex], account, entries[index].record, false));
        }
      }
    }
  }
}

function findNote(app, noteId) {
  const accounts = allAccounts(app);
  for (let accountIndex = 0; accountIndex < accounts.length; accountIndex += 1) {
    const account = accounts[accountIndex];
    const entries = folderEntries(account);
    for (let folderIndex = 0; folderIndex < entries.length; folderIndex += 1) {
      const notes = directNotes(entries[folderIndex].folder);
      for (let noteIndex = 0; noteIndex < notes.length; noteIndex += 1) {
        if (objectId(notes[noteIndex]) === noteId) {
          return { note: notes[noteIndex], account: account, folder: entries[folderIndex].record };
        }
      }
    }
  }
  toolError("NOTE_NOT_FOUND", "Apple Note was not found: " + noteId);
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function textToHtml(text) {
  if (!text) return "";
  return String(text).split(/\r?\n/).map(function (line) {
    return line ? "<div>" + escapeHtml(line) + "</div>" : "<div><br></div>";
  }).join("");
}

function contentHtml(params) {
  return params.content_format === "html" ? String(params.content) : textToHtml(params.content);
}

function noteBody(title, content) {
  const heading = "<div><b>" + escapeHtml(title) + "</b></div>";
  return content ? heading + "<div><br></div>" + content : heading;
}

function handle(app, action, params) {
  if (action === "health") {
    const accounts = allAccounts(app);
    const defaultAccount = findAccount(app, null, true);
    return {
      ok: true,
      application: String(safeValue(function () { return app.name(); }, "Notes")),
      version: String(safeValue(function () { return app.version(); }, "")),
      account_count: accounts.length,
      default_account: defaultAccount ? accountRecord(defaultAccount) : null
    };
  }

  if (action === "list_accounts") {
    return allAccounts(app).map(accountRecord);
  }

  if (action === "list_folders") {
    const accounts = params.account
      ? [findAccount(app, params.account, false)]
      : allAccounts(app);
    let records = [];
    accounts.forEach(function (account) {
      records = records.concat(folderEntries(account).map(function (entry) { return entry.record; }));
    });
    return records;
  }

  if (action === "list_notes") {
    let accounts;
    if (params.account) {
      accounts = [findAccount(app, params.account, false)];
    } else if (params.folder || params.folder_id) {
      accounts = [findAccount(app, null, true)];
    } else {
      accounts = allAccounts(app);
    }
    let records = [];
    const seen = {};
    accounts.forEach(function (account) {
      if (params.folder || params.folder_id) {
        const selected = findFolder(account, params.folder, params.folder_id, false);
        collectFolderNotes(selected, account, Boolean(params.recursive), records, seen);
      } else {
        const entries = folderEntries(account);
        entries.forEach(function (entry) {
          collectFolderNotes(entry, account, false, records, seen);
        });
      }
    });
    if (params.query) {
      const query = String(params.query).toLocaleLowerCase();
      records = records.filter(function (record) {
        return record.name.toLocaleLowerCase().indexOf(query) >= 0;
      });
    }
    records.sort(function (left, right) {
      return String(right.modified_at || "").localeCompare(String(left.modified_at || ""));
    });
    const offset = Number(params.offset || 0);
    const limit = Number(params.limit || 100);
    return records.slice(offset, offset + limit);
  }

  if (action === "get_note") {
    const found = findNote(app, String(params.note_id));
    return noteRecord(found.note, found.account, found.folder, true);
  }

  if (action === "create_note") {
    const account = findAccount(app, params.account, true);
    if (!account) toolError("ACCOUNT_NOT_FOUND", "No Apple Notes account is available.");
    const selected = findFolder(account, params.folder, params.folder_id, true);
    if (!selected) toolError("FOLDER_NOT_FOUND", "No writable Apple Notes folder is available.");
    const body = noteBody(String(params.title), contentHtml(params));
    const note = app.Note({ body: body });
    selected.folder.notes.push(note);
    return noteRecord(note, account, selected.record, true);
  }

  if (action === "update_note") {
    const found = findNote(app, String(params.note_id));
    const fragment = contentHtml(params);
    if (params.mode === "append") {
      const existing = String(safeValue(function () { return found.note.body(); }, ""));
      found.note.body = existing + (existing && fragment ? "<div><br></div>" : "") + fragment;
    } else {
      found.note.body = params.preserve_title
        ? noteBody(objectName(found.note), fragment)
        : fragment;
    }
    return noteRecord(found.note, found.account, found.folder, true);
  }

  toolError("UNKNOWN_ACTION", "Unknown Notes action: " + action);
}

function run() {
  try {
    const request = readRequest();
    const app = Application("Notes");
    app.includeStandardAdditions = false;
    return JSON.stringify({
      ok: true,
      result: handle(app, String(request.action || ""), request.params || {})
    });
  } catch (error) {
    const message = String(error.message || error);
    let code = error.toolCode || "AUTOMATION_FAILED";
    if (message.indexOf("-1743") >= 0 || /not authorized/i.test(message)) {
      code = "AUTOMATION_PERMISSION_DENIED";
    }
    return JSON.stringify({
      ok: false,
      error: { code: String(code), message: message }
    });
  }
}
