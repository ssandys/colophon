import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  // bin/dev rewrites the identity in the deployed copy only; the source tree
  // stays canonical. It derives its targets rather than naming them -- every
  // deployed file that is text -- so moving these into another file no longer
  // strands them. That breadth was learned the hard way twice: see AGENTS.md's
  // devkit section and issue #5.
  moduleName: "ssandys.colophon"
  ipcTarget: "ssandys.colophon"

  readonly property string barIcon: Model.BAR_GLYPH
  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : "JetBrainsMono Nerd Font"

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0)
      return decodeURIComponent(value.substring(7))
    return value
  }

  // Persist a widget setting the way omarchy.power persists its percentage
  // toggle: patch the inline shell.json entry via the shell, and update this
  // panel's own settings object in the same breath so Service.qml (which binds
  // to it) sees the new value without waiting for a reload. updateEntryInline
  // diffs before writing, so setting the same value twice does not dirty
  // shell.json.
  function setContextSize(value) {
    root.settings = Object.assign({}, root.settings, { contextSize: value })
    if (root.bar && root.bar.shell)
      root.bar.shell.updateEntryInline(root.moduleName, root.settings)
  }

  // The commit action, on slider release or field edit-finish: persist the
  // size and ask the service to re-stamp every installed model's default
  // num_ctx with it. That rewrite is what lets clients that never send
  // num_ctx -- opencode, which only speaks Ollama's /v1 endpoint -- load at
  // the chosen context. runAction deduplicates a repeat of the last size it
  // successfully applied, so a no-move drag does not churn the models again.
  function commitContextSize(value) {
    root.setContextSize(value)
    service.runAction("apply-context", String(value), "")
  }

  readonly property var snap: service.snapshot
  readonly property string status: service.effectiveStatus

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Service {
    id: service
    settings: root.settings
    panelOpen: root.opened
    collectPath: root.pathFromUrl(Qt.resolvedUrl("scripts/colophon_collect.py"))
    actionPath: root.pathFromUrl(Qt.resolvedUrl("scripts/colophon_action.py"))
  }

  onOpenedChanged: {
    if (opened) {
      service.actionError = ""
      service.refresh()
    }
  }

  // BarIconButton, not WidgetButton: WidgetButton is for text labels, and it
  // centres the glyph's *advance box* via anchors.centerIn. The bar font is
  // monospace with a 7.80px advance cell, but every Nerd Font icon overflows
  // that cell to the right only -- U+EE86 has 12.00px of ink starting at the
  // pen origin -- so the ink landed about (12.00 - 7.80) / 2 = 2.10 logical px
  // right of the slot centre, while the open-panel mark sat correctly centred
  // on the slot. The mark was never wrong; the glyph was.
  //
  // BarIconButton wraps Ui/OpticalGlyph.qml, which corrects horizontal
  // position by the delta between advance centre and painted-ink centre. Every
  // other icon-only bar widget already uses it. It extends WidgetButton, so
  // bar, text, foreground, tooltipText and onPressed all carry over unchanged.
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barIcon
    foreground: {
      var severity = Model.barSeverity(root.status)
      if (severity === "error") return "#ef4444"
      if (severity === "warn") return "#eab308"
      if (severity === "dim") return root.dim
      // Bar chrome convention: barForeground for the glyph, foreground for
      // panel content. Without this, a transparent bar recolors every
      // neighbouring widget for legibility except this one.
      return root.barForeground
    }
    // No fixedWidth/fixedHeight here: BarIconButton sets both from
    // Style.bar.iconSlot, whose default is the same 27 this used to hardcode --
    // but the token honours a theme's icon-slot / icon-canvas / icon-font
    // overrides, which a literal silently ignored.
    tooltipText: Model.tooltipText(root.snap, service.nowSec)
    onPressed: function (which) {
      if (which === Qt.MiddleButton) {
        // Asymmetric on purpose: a start is harmless, a stop could kill a
        // running generation on a stray middle-click. Documented in the README.
        if (Model.canStart(root.status, service.actionInProgress))
          service.runAction("start", "", "")
        else service.refresh()
        return
      }
      if (root.opened) root.close()
      else root.open()
    }

    BorderSurface {
      visible: badgeLabel.text !== ""
      width: Math.max(9, button.fontSize * 0.85)
      height: width
      radius: width / 2
      color: Color.accent
      borderSpec: Border.flat(Color.background, 1)
      anchors.horizontalCenter: parent.horizontalCenter
      // glyphPaintedWidth, not labelWidth: BarIconButton sets labelVisible to
      // false, so labelWidth is 0 there and the badge would collapse onto the
      // glyph's own centre. This is load-bearing, not cosmetic.
      anchors.horizontalCenterOffset: button.glyphPaintedWidth / 2
      anchors.verticalCenter: parent.verticalCenter
      anchors.verticalCenterOffset: -button.fontSize * 0.5

      Text {
        id: badgeLabel
        anchors.centerIn: parent
        text: Model.badgeText(root.snap)
        color: Color.background
        font.family: root.fontFamily
        font.bold: true
        font.pixelSize: Math.max(6, parent.height * 0.66)
        renderType: Text.NativeRendering
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(430))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTextKey: function (t) {
        if (t === "r" || t === "R") {
          service.actionError = ""
          service.refresh()
        }
      }

      ColumnLayout {
        id: contentColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(8)

        // ── Header ──
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(8)

          Text {
            text: root.barIcon + "  Colophon"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }

          Text {
            // Server version when running, client version otherwise -- the
            // header is never blank, because `ollama --version` reports the
            // client version even with the server down.
            text: {
              var api = root.snap.api
              if (!api) return ""
              if (api.serverVersion) return "ollama " + api.serverVersion
              if (api.clientVersion) return "ollama " + api.clientVersion + " client"
              return ""
            }
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        PanelSeparator { Layout.fillWidth: true; foreground: root.fg }

        // ── Status ──
        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          Text {
            text: Model.statusDot(root.status)
            color: Model.dotColor(root.status, root.dim)
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Text {
            text: {
              var label = Model.statusLabel(root.status, service.secondsInStatus)
              var pieces = [label]
              if (root.status === "running") {
                var up = Model.uptimeSeconds(root.snap, service.nowSec)
                if (up !== null) pieces.push("up " + Model.formatDuration(up))
                var memory = root.snap.unit ? root.snap.unit.memoryBytes : null
                if (memory) pieces.push(Model.formatBytes(memory))
              }
              if (root.status === "failed" && root.snap.unit &&
                  root.snap.unit.result)
                pieces.push(root.snap.unit.result)
              return pieces.join(" · ")
            }
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            Layout.fillWidth: true
            elide: Text.ElideRight
          }

          Text {
            visible: root.snap.summary && root.snap.summary.loadedCount > 0
            text: Model.plural(root.snap.summary
              ? root.snap.summary.loadedCount : 0, "model") + " loaded"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        // Boot state, and the switch that changes it. enable/disable go
        // through manage-unit-files, which systemd invokes with no `unit`
        // detail, so no polkit rule could ever scope it to this one unit --
        // which is why this was read-only until 2026-08-12. Colophon installs
        // no rule any more; it prompts. Prompted authorization has nothing to
        // scope, so the missing detail stopped mattering. See AGENTS.md #28.
        RowLayout {
          Layout.fillWidth: true
          Layout.leftMargin: Style.space(14)
          spacing: Style.space(6)
          visible: bootText.text !== "" && root.status !== "missing"

          Text {
            id: bootText
            text: Model.bootLabel(root.snap.unit ? root.snap.unit.unitFileState : "")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Item { Layout.fillWidth: true }

          ToggleSwitch {
            id: bootSwitch

            // Hidden for masked, static, enabled-runtime and anything else
            // systemd will not simply flip -- those states show their label
            // and offer no control.
            visible: Model.bootIsToggleable(
                       root.snap.unit ? root.snap.unit.unitFileState : "")

            // The optimistic value when one is set, reality otherwise: the
            // knob throws the instant it is clicked rather than waiting a
            // poll. ToggleSwitch's own docs describe this pattern.
            checked: service.optimisticBootState !== ""
                     ? service.optimisticBootState === "enabled"
                     : (root.snap.unit
                        ? root.snap.unit.unitFileState === "enabled"
                        : false)

            // Swallows further clicks while a verb is in flight without
            // dropping hover or tooltips on a background refresh.
            busy: service.actionInProgress !== ""

            foreground: root.fg

            onToggled: service.runAction(checked ? "disable" : "enable", "", "")

            // ToggleSwitch has no tooltipText property -- Button does, but this
            // is not a Button. PanelToolTip is the shell's drop-in for exactly
            // this: declare it inside the hovered item and bind `visible` to
            // the hover state. ToggleSwitch exposes `containsMouse` as a
            // readonly alias for that purpose.
            PanelToolTip {
              visible: bootSwitch.containsMouse
              text: "Start ollama.service at boot -- does not start it now"
              fontFamily: root.fontFamily
            }
          }
        }

        Text {
          visible: Model.actionDisabledReason(root.status) !== ""
          text: Model.actionDisabledReason(root.status)
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
          Layout.leftMargin: Style.space(14)
        }

        // ── Lifecycle actions ──
        RowLayout {
          Layout.fillWidth: true
          Layout.leftMargin: Style.space(14)
          spacing: Style.space(4)

          Button {
            // Hidden in `foreign` too: something is already serving, and the
            // spec's mockup for that state shows only stop and restart.
            visible: root.status !== "running" && root.status !== "starting" &&
                     root.status !== "foreign"
            text: "start"
            foreground: "#22c55e"
            tooltipText: Model.actionDisabledReason(root.status) ||
                         "Start ollama.service"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(2)
            enabled: Model.canStart(root.status, service.actionInProgress)
            opacity: enabled ? 1.0 : 0.4
            onClicked: service.runAction("start", "", "")
          }

          Button {
            visible: root.status === "running" || root.status === "starting" ||
                     root.status === "foreign"
            text: "stop"
            foreground: root.fg
            tooltipText: Model.actionDisabledReason(root.status) ||
                         "Stop ollama.service"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(2)
            enabled: Model.canStop(root.status, service.actionInProgress)
            opacity: enabled ? 1.0 : 0.4
            onClicked: service.runAction("stop", "", "")
          }

          Button {
            visible: root.status !== "stopped" && root.status !== "missing"
            text: "restart"
            foreground: root.fg
            tooltipText: Model.actionDisabledReason(root.status) ||
                         "Restart ollama.service"
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            horizontalPadding: Style.space(6)
            verticalPadding: Style.space(2)
            enabled: Model.canRestart(root.status, service.actionInProgress)
            opacity: enabled ? 1.0 : 0.4
            onClicked: service.runAction("restart", "", "")
          }

          Text {
            visible: service.actionInProgress !== ""
            text: "working…"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Item { Layout.fillWidth: true }
        }

        // ── Context window ──
        // How much context a warmed model gets (Ollama's num_ctx, in tokens).
        // The slider moves over the INDEX of Model.js's CONTEXT_STEPS, so it
        // can only land on a power of two. Dragging persists the size live for
        // the next warm; RELEASING (or finishing an edit in the field) commits
        // it, which also re-stamps every installed model's default num_ctx so
        // clients that never send the option load at this size too.
        RowLayout {
          Layout.fillWidth: true
          Layout.leftMargin: Style.space(14)
          Layout.rightMargin: Style.space(14)
          spacing: Style.space(6)

          Text {
            text: "context"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          PanelSlider {
            id: contextSlider
            bar: root.bar
            Layout.fillWidth: true
            minimum: 0
            maximum: Model.contextCount() - 1
            step: 1
            integer: true
            tickCount: Model.contextCount()
            value: Model.contextIndex(service.contextSize)
            onMoved: function (index) {
              root.setContextSize(Model.contextAt(index))
            }
            onReleased: function (index) {
              root.commitContextSize(Model.contextAt(index))
            }
          }

          // The number is editable: click it to type a value in range -- a
          // plain number like 18000 is sent exactly, while k shorthand is a
          // binary thousand (16k is 16384, 24k is 24576). The slider knob
          // still snaps to the nearest step for position, but the committed
          // value is sent to Ollama exactly. text is re-bound to the setting
          // whenever editing finishes so a slider drag or the settings panel
          // keeps it live. No IntValidator here: it would block the "k" in
          // 16k at the keyboard, so acceptance happens in
          // Model.parseContextSize on commit, with garbage reverting the
          // field to the current value.
          TextField {
            id: contextField
            text: String(service.contextSize)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            color: root.fg
            horizontalPadding: Style.space(4)
            verticalPadding: 3
            implicitWidth: 44
            horizontalAlignment: TextInput.AlignRight

            function syncToSetting() {
              text = Qt.binding(function () {
                return String(service.contextSize)
              })
            }

            onEditingFinished: {
              var value = Model.parseContextSize(text)
              if (isNaN(value)) {
                syncToSetting()
                return
              }
              value = Math.max(4096, Math.min(131072, value))
              root.commitContextSize(value)
              syncToSetting()
            }
          }
        }

        // ── Error strip ──
        // stopped, failed, and missing are STATES, rendered above with no error
        // styling. This strip means the widget itself could not find out.
        Text {
          visible: text !== ""
          text: service.actionError || service.collectorError
          color: "#ef4444"
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          Layout.fillWidth: true
          wrapMode: Text.WordWrap
        }

        // ── Loaded models ──
        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.fg
          visible: loadedSection.visible
        }

        ColumnLayout {
          id: loadedSection
          Layout.fillWidth: true
          spacing: Style.space(2)
          // Hidden entirely when nothing is serving: there is nothing true to
          // say about loaded models when the server is down.
          visible: root.status === "running" || root.status === "foreign"

          Text {
            text: "LOADED"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }

          Text {
            visible: (root.snap.loaded || []).length === 0
            text: "No models loaded"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            Layout.leftMargin: Style.space(14)
          }

          // Capped and scrolling for the same reason the installed list is.
          // KeyboardPanel clamps the CARD's height, but the Item holding its
          // content neither clips nor scrolls, so an uncapped list pushes the
          // sections below it -- and the footer -- off the visible card with no
          // way to reach them. The installed list was protected and this one
          // was not; both need it.
          ScrollView {
            id: loadedScroll
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(loadedColumn.implicitHeight,
                                             Style.space(120))
            clip: true
            visible: (root.snap.loaded || []).length > 0
            // Inside a QQuickScrollView the content child is reparented
            // under the Flickable's content item, whose width IS
            // contentWidth -- so a plain `width: parent.width` sizes the
            // column to its natural width, not the space actually
            // available, and Layout.fillWidth + elide on the row Text has
            // nothing to fill against. availableWidth is the idiom the
            // shell's own monitor/audio panels use for exactly this.
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
              id: loadedColumn
              width: loadedScroll.availableWidth
              spacing: Style.space(2)

              Repeater {
                model: root.snap.loaded || []

                RowLayout {
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  spacing: Style.space(6)

                  Text {
                    text: modelData.name
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                  }

                  Text {
                    text: Model.formatBytes(modelData.sizeBytes)
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    text: Model.processorLabel(modelData)
                    color: modelData.processor === "gpu" ? "#22c55e" : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Text {
                    visible: modelData.expiresAt !== null &&
                             modelData.expiresAt !== undefined
                    text: Model.formatCountdown(
                      Number(modelData.expiresAt) - service.nowSec)
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }

                  Button {
                    text: "✕"
                    foreground: "#ef4444"
                    tooltipText: "Unload this model, freeing its memory"
                    fontFamily: root.fontFamily
                    fontSize: Style.font.caption
                    horizontalPadding: Style.space(6)
                    verticalPadding: Style.space(2)
                    enabled: service.actionInProgress === ""
                    opacity: enabled ? 1.0 : 0.4
                    onClicked: service.runAction("unload", modelData.name,
                                                 modelData.kind)
                  }
                }
              }
            }

            // The inner Flickable must only claim wheel/drag input when the
            // content actually overflows -- otherwise a short list still
            // swallows scroll events the panel's outer view should get.
            Binding {
              target: loadedScroll.contentItem
              property: "interactive"
              value: loadedColumn.implicitHeight > loadedScroll.height
            }
          }
        }

        // ── Installed models ──
        PanelSeparator {
          Layout.fillWidth: true
          foreground: root.fg
          visible: installedSection.visible
        }

        ColumnLayout {
          id: installedSection
          Layout.fillWidth: true
          spacing: Style.space(2)
          visible: service.showInstalledModels

          RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(6)

            Text {
              text: {
                var summary = root.snap.summary
                if (!summary) return "INSTALLED"
                return "INSTALLED · " + summary.installedCount + " · " +
                       Model.formatBytes(summary.installedBytes)
              }
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              Layout.fillWidth: true
            }

            Text {
              visible: root.status !== "missing"
              text: "click a model to run it"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Text {
            visible: (root.snap.installed || []).length === 0
            text: "No models installed"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            Layout.leftMargin: Style.space(14)
          }

          // Scrolls within a capped height, so a machine with forty models
          // does not produce a panel taller than the screen.
          ScrollView {
            id: installedScroll
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(installedColumn.implicitHeight,
                                             Style.space(190))
            clip: true
            // See loadedScroll above: availableWidth, not parent.width, is
            // what keeps a long row from widening this ScrollView instead
            // of staying inside it.
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
              id: installedColumn
              width: installedScroll.availableWidth
              spacing: Style.space(2)

              Repeater {
                model: root.snap.installed || []

                Button {
                  id: installedButton
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  // One click: start the server if needed, wait for the port,
                  // then warm the model. You rarely want "the server" -- you
                  // want a model.
                  //
                  // The label is a single space, not "" -- Button's Row skips
                  // any child made invisible by `visible: text !== ""`
                  // entirely, so an empty label collapses row.implicitHeight
                  // (and with it the button's implicitHeight) to 0. A
                  // one-character label keeps that Text visible, which keeps
                  // the row's real line-height, and paints nothing since a
                  // space has no ink -- confirmed with a headless qml probe
                  // (see the SDD report). leftAlign is dropped: with no
                  // visible label left to position, it no longer does
                  // anything.
                  text: " "
                  foreground: root.fg
                  tooltipText: {
                    var bits = [modelData.name]
                    if (modelData.parameterSize) bits.push(modelData.parameterSize)
                    if (modelData.quantization) bits.push(modelData.quantization)
                    if (modelData.family) bits.push(modelData.family)
                    return bits.join(" · ") + " — click to load"
                  }
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  horizontalPadding: Style.space(6)
                  verticalPadding: Style.space(2)
                  enabled: service.actionInProgress === "" &&
                           root.status !== "missing" &&
                           root.status !== "foreign"
                  opacity: enabled ? 1.0 : 0.4
                  onClicked: service.runAction("warm", modelData.name,
                                               modelData.kind)

                  // Same idiom as the bar-glyph badge in the BarIconButton
                  // above: plain Text children painted over the clickable
                  // surface. No MouseArea here, so click-to-load, hover, and
                  // the tooltip all keep working straight through. Anchored
                  // to the button's own reserved content insets so the text
                  // lines up with where the concatenated label used to sit,
                  // rather than flush against the border.
                  RowLayout {
                    anchors.left: installedButton.left
                    anchors.leftMargin: installedButton._reservedContentLeftInset
                    anchors.right: installedButton.right
                    anchors.rightMargin: installedButton._reservedBorderRight +
                                          installedButton.horizontalPadding
                    anchors.verticalCenter: installedButton.verticalCenter
                    spacing: Style.space(6)

                    Text {
                      text: modelData.name
                      color: root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      Layout.fillWidth: true
                      elide: Text.ElideRight
                    }

                    Text {
                      text: service.actionInProgress === "warm:" + modelData.name
                        ? "warming…" : Model.formatBytes(modelData.sizeBytes)
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }
            }

            Binding {
              target: installedScroll.contentItem
              property: "interactive"
              value: installedColumn.implicitHeight > installedScroll.height
            }
          }
        }

        PanelSeparator { Layout.fillWidth: true; foreground: root.fg }

        Text {
          Layout.fillWidth: true
          horizontalAlignment: Text.AlignHCenter
          text: "r refresh · esc closes"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
