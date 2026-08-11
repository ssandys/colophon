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
  // bin/install rewrites these two, and only these two, on the way to the dev
  // install. Do not move them into Service.qml without updating that script
  // and its verification grep.
  moduleName: "ssandys.colophon"
  ipcTarget: "ssandys.colophon"

  readonly property string barIcon: "\uF2DB"
  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : "JetBrainsMono Nerd Font"

  function pathFromUrl(url) {
    var value = String(url || "")
    if (value.indexOf("file://") === 0)
      return decodeURIComponent(value.substring(7))
    return value
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

  WidgetButton {
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
    fixedWidth: root.bar && root.bar.vertical ? -1 : Style.space(27)
    fixedHeight: root.bar && root.bar.vertical ? Style.space(26) : -1
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
      anchors.horizontalCenterOffset: button.labelWidth / 2
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

        // The one thing systemd tells us that this widget deliberately cannot
        // change: enable/disable goes through manage-unit-files, which polkit
        // cannot scope to a single unit. README gives the one-time command.
        Text {
          visible: text !== "" && root.status !== "missing"
          text: Model.bootLabel(root.snap.unit ? root.snap.unit.unitFileState : "")
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          Layout.leftMargin: Style.space(14)
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
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  leftAlign: true
                  // One click: start the server if needed, wait for the port,
                  // then warm the model. You rarely want "the server" -- you
                  // want a model.
                  text: {
                    var label = modelData.name
                    var pad = Model.formatBytes(modelData.sizeBytes)
                    if (service.actionInProgress === "warm:" + modelData.name)
                      return label + "   warming…"
                    return label + "   " + pad
                  }
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
