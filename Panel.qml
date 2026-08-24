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

  readonly property var snap: service.snapshot
  readonly property string status: service.effectiveStatus

  // Count of TextFields with active focus, not a bool: the parameter editor
  // instantiates one field per applicable spec (up to two, kind-filtered by
  // paramSpecsFor) and each one's onActiveFocusChanged fires independently
  // on both edges. A bool set by
  // whichever fires last is order-dependent by construction -- Tab from
  // field 1 to field 2 fires both handlers, and if the loser's false-write
  // lands after the gainer's true-write, the flag reads false while a field
  // still holds focus. A counter that increments on focus gained and
  // decrements on focus lost stays nonzero across the hand-off regardless
  // of which of the two events lands last (it reads 2 transiently, then
  // settles at 1, never touching 0). PanelKeyCatcher binds `blocked` to
  // this being nonzero so j/k/h/l, Enter and Escape reach the focused field
  // instead of the panel's own key handling -- see the header comment on
  // PanelKeyCatcher and the three first-party panels (network, clock,
  // weather) that already do this for their own inline editors.
  property int paramFieldsFocused: 0

  // Which installed model has its editor expanded, by name. One at a time:
  // the list is height-capped and clips, so two open editors would mean
  // scrolling inside a scroll to reach the second one's apply.
  property string expandedModel: ""

  readonly property var expandedEntry: {
    var list = root.snap.installed || []
    for (var i = 0; i < list.length; i++)
      if (list[i].name === root.expandedModel) return list[i]
    return null
  }

  // Guards against paramFieldsFocused drifting upward: collapsing the old
  // row (choosing a different model, or none) tears down its TextFields
  // without necessarily running their onActiveFocusChanged(false) first, so
  // resetting here is what keeps the count from sticking above zero and
  // leaving PanelKeyCatcher permanently blocked.
  //
  // This reset is belt-and-braces, not the primary mechanism. The field's own
  // `onVisibleChanged` releases focus whenever the editor is hidden, which
  // fires the decrement, and that covers paths this handler cannot see --
  // notably the server stopping mid-edit, which hides the editor (its
  // `visible` also gates on root.status) without expandedModel changing at
  // all. Probe-verified on that exact path: focus a field, drop status to
  // stopped, and the count lands at 0 with the catcher unblocked. Both are
  // kept because the failure mode is a panel whose keyboard stops working,
  // and the clamp below makes the overlap harmless.
  onExpandedModelChanged: root.paramFieldsFocused = 0

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
      // Freeze the panel's own key handling while a parameter field owns
      // input -- otherwise lowercase j/k/h/l vanish into cursor movement,
      // Enter never reaches onEditingFinished, and Escape closes the whole
      // panel instead of just reverting the field.
      blocked: root.paramFieldsFocused > 0
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

                // The delegate's root used to be `installedButton` itself.
                // It no longer can be: the parameter editor below needs to
                // sit beside the button, never inside it, because the
                // button's whole surface is a click-to-warm target. Putting
                // the editor's TextFields inside that surface would mean
                // clicking a field to edit it also fires a multi-gigabyte
                // model load.
                // A Repeater delegate permits exactly one root, so that root
                // is now this ColumnLayout, and Layout.fillWidth /
                // Layout.leftMargin -- previously the button's own -- move
                // here. The button keeps everything else (id included, so
                // _reservedContentLeftInset below still resolves) unchanged.
                ColumnLayout {
                  Layout.fillWidth: true
                  Layout.leftMargin: Style.space(14)
                  spacing: Style.space(2)

                  // Name/size and `config` share ONE row. They used to be two
                  // stacked rows, which cost every model a permanent second
                  // line -- eleven models meant twenty-two rows inside a list
                  // capped at Style.space(190), so the list mostly scrolled.
                  // `config` still cannot live INSIDE installedButton (that
                  // surface is the click-to-warm target), so it is a sibling
                  // here and the button takes the slack via fillWidth.
                  RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.space(6)

                      Button {
                        id: installedButton
                      // The button no longer gets its own leftMargin -- the
                      // new root above carries it for the whole row -- but it
                      // still needs fillWidth of its own: a ColumnLayout only
                      // stretches a child to its own width when that child
                      // asks for it, so without this the button would shrink
                      // to its label's implicit width and the name/size row
                      // anchored inside it would be clipped to match.
                      Layout.fillWidth: true
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

                    // Expand trigger. A sibling of installedButton, never a
                    // child of it -- the delegate root above is a ColumnLayout
                    // holding installedButton and this as siblings, so this
                    // has no path to installedButton.onClicked and cannot
                    // fire a warm no matter how it's clicked. An earlier
                    // version of this row used installedButton.onRightClicked
                    // for the same toggle to avoid adding anything to the
                    // visual tree at all, but the owner overruled that: right
                    // click has no visible affordance, so nothing on screen
                    // told anyone this existed. This is the plain, unbordered
                    // Button already used everywhere else in this panel for a
                    // small action (apply below, start/stop/restart above,
                    // the loaded list's ✕) -- dim and caption-sized so a
                    // permanent line per model doesn't dominate the list.
                    // Button's own `focusable` defaults to false, so it never
                    // becomes a Tab stop between the parameter fields.
                    Button {
                      // No leftMargin: it sits at the end of the row, after
                      // installedButton has taken the slack via fillWidth, so
                      // it lands just right of the model's size. It briefly
                      // had a Style.space(14) from when it was a row of its
                      // own beneath the model -- stacked on the delegate
                      // root's own margin, that pushed its label 14px past the
                      // name, which is what read as misalignment on screen.
                      // Nothing here needs to align now, but the padding is
                      // still deliberately Style.space(6), matching
                      // installedButton so the two labels share a baseline
                      // rhythm rather than one looking taller than the other.
                      text: "config"
                      foreground: root.dim
                      tooltipText: (root.expandedModel === modelData.name
                                    ? "Hide" : "Show") + " this model's parameters"
                      fontFamily: root.fontFamily
                      fontSize: Style.font.caption
                      horizontalPadding: Style.space(6)
                      verticalPadding: Style.space(2)
                      onClicked: root.expandedModel =
                        (root.expandedModel === modelData.name ? "" : modelData.name)
                    }
                  }


                  // Expanded parameter editor. A sibling of installedButton,
                  // never a child -- see the comment on the root ColumnLayout
                  // above. Hidden unless this row is the expanded one AND the
                  // server is up: both reading the values and writing them
                  // need the daemon, and every other control in this panel
                  // already gates on status.
                  ColumnLayout {
                    id: paramEditor
                    Layout.fillWidth: true
                    // Also no leftMargin -- see the config Button above. The
                    // rows inside indent themselves to the button's content
                    // inset instead, so labels, "config", "apply" and the
                    // model name all share one left edge.
                    spacing: Style.space(2)
                    visible: root.expandedModel === modelData.name &&
                             root.status === "running"

                    // The specs this model's KIND can use, hoisted once per
                    // row rather than recomputed by both the Repeater's model
                    // count and its delegate below. modelData.kind is a real
                    // collector row key (tests/test_cross_language.py's
                    // installed-row check greps this section for
                    // `modelData.*` and cross-checks every hit against the
                    // collector's row keys), so referencing it here is safe.
                    // A kind the collector could not classify yields an empty
                    // array from Model.paramSpecsFor, hiding the editor's
                    // rows entirely rather than showing inapplicable fields
                    // disabled.
                    //
                    // Referenced below as paramEditor.editableSpecs, never
                    // bare -- QML does not walk arbitrary ancestor objects to
                    // resolve an unqualified name; it resolves against the
                    // object itself, the component root, and declared ids.
                    // This ColumnLayout is neither, so the Repeater's model
                    // and its delegate (a fresh component instantiation per
                    // row) cannot see a bare `editableSpecs` -- it must go
                    // through this id. Caught only by a headless qml6 probe
                    // run with QT_FORCE_STDERR_LOGGING=1: the bare form fails
                    // as a runtime ReferenceError on stderr, not a load
                    // failure, so qmlformat and qmllint both stay silent.
                    readonly property var editableSpecs:
                      Model.paramSpecsFor(modelData.kind)

                    // Width of the label column, measured rather than guessed:
                    // a fixed Style.space() would drift the moment a theme
                    // changes the font, and the previous Layout.fillWidth on
                    // each label stretched it until the value box hit the
                    // panel's right edge -- most of the panel's width sitting
                    // empty between "temperature" and its own value. Deriving
                    // the widest label from PARAM_SPECS keeps this correct if a
                    // parameter is ever added or renamed.
                    TextMetrics {
                      id: paramLabelMetrics
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      text: Model.PARAM_SPECS.reduce(function (widest, spec) {
                        return spec.label.length > widest.length ? spec.label
                                                                : widest
                      }, "")
                    }

                    // Width of the value column: the widest string a field can
                    // DISPLAY, which is not the widest value it can hold. The
                    // range placeholder "4096–131072" is 11 characters where
                    // num_ctx's own ceiling is 6, and sizing from the value
                    // alone is what elided the placeholder to "4096–1…" on
                    // screen. Ranges do not always win either -- temperature's
                    // "0–2" is shorter than values it will hold -- so this
                    // takes the longest of every string any field renders,
                    // asking Model for each rather than restating it here.
                    // Length is a sound proxy for width only because the panel
                    // is monospace throughout.
                    TextMetrics {
                      id: paramValueMetrics
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      text: Model.PARAM_SPECS.reduce(function (widest, spec) {
                        var shown = [Model.formatParamRange(spec.key),
                                     Model.formatParamValue(spec.key, spec.min),
                                     Model.formatParamValue(spec.key, spec.max)]
                        for (var i = 0; i < shown.length; i++)
                          if (shown[i].length > widest.length)
                            widest = shown[i]
                        return widest
                      }, "")
                    }

                    Repeater {
                      // An index-count model, not paramEditor.editableSpecs
                      // itself: this Repeater nests inside the one iterating
                      // installed rows, and QML's Repeater injects the same implicit
                      // `modelData` name for every array model regardless of
                      // nesting depth. tests/test_cross_language.py's
                      // installed-row check greps this whole section for
                      // `modelData.*` and cross-checks every hit against the
                      // collector's row keys -- a spec's own `key`/`label`
                      // would read as a phantom row field and fail that
                      // check. Looking specs up by index sidesteps the
                      // collision instead of fighting it.
                      model: paramEditor.editableSpecs.length

                      // The delegate root is this RowLayout directly. It was
                      // briefly a ColumnLayout wrapping the row plus a caption
                      // on its own line; with the caption moved inline the
                      // wrapper had one child and nothing to space, so it is
                      // gone. `spec` lives here now -- note that the fields
                      // below reach it as specRow.spec, an id, which resolves
                      // from anywhere in this component. An unqualified `spec`
                      // would NOT: QML resolves unqualified names against the
                      // object itself, the component root and declared ids
                      // only, never arbitrary ancestors. That distinction is
                      // what broke paramEditor.editableSpecs once already.
                      RowLayout {
                        id: specRow
                        readonly property var spec: paramEditor.editableSpecs[index]
                        Layout.fillWidth: true
                        // Indents the label/value pair to exactly where
                        // installedButton paints the model name -- the same
                        // anchor the name/size row above uses. Per trap 29
                        // this is a private upstream property: if it ever
                        // disappears the margin resolves to 0 and these rows
                        // go flush with the button's border instead of lining
                        // up under the name. Cosmetic, not a crash.
                        Layout.leftMargin:
                          installedButton._reservedContentLeftInset
                        spacing: Style.space(6)

                        Text {
                          text: specRow.spec.label
                          color: root.dim
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          // A measured column, not fillWidth. fillWidth kept
                          // the value boxes in a straight column too, but only
                          // by stretching each label until its own value sat
                          // against the panel's right edge. Pinning the label
                          // width instead keeps that column straight AND lets
                          // the value sit beside its label.
                          Layout.preferredWidth: paramLabelMetrics.width
                        }

                        TextField {
                          id: paramField
                          readonly property string paramKey: specRow.spec.key

                          text: service.paramEditText(root.expandedEntry, paramKey)
                          // An unset field is the MAIN case, not an edge
                          // case -- num_ctx is blank on every generative
                          // model in the owner's real store -- so the valid
                          // range doubles as the field's own explanation of
                          // what it will accept. The dim caption Text below
                          // covers WHAT the parameter does; this covers
                          // what values are legal.
                          placeholderText: Model.formatParamRange(paramKey)
                          foreground: root.fg
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          horizontalAlignment: TextInput.AlignRight
                          // TextField's own header comment: "the default 30px
                          // implicitHeight fits dialog forms; inline callers
                          // (wifi's row-embedded passphrase prompt) drop
                          // verticalPadding to match a 22-26px row." This is
                          // an inline caller and was using the dialog default,
                          // which is why four fields cost ~190px of a list
                          // capped at Style.space(190). controlGap/xs land it
                          // at the bottom of that documented range.
                          horizontalPadding: Style.spacing.controlGap
                          verticalPadding: Style.spacing.xs
                          implicitWidth: paramValueMetrics.width +
                                         horizontalPadding * 2 + Style.space(4)

                          // Qt does NOT clear activeFocus when an item is
                          // hidden -- verified by headless qml6 probe, three
                          // deterministic runs. Without this, collapsing a row
                          // while a field held focus left activeFocus stuck
                          // true with no signal, so the counter below never
                          // decremented; re-expanding then read
                          // paramFieldsFocused === 0 while a field really did
                          // have focus, and PanelKeyCatcher stole k/j/h/l,
                          // Enter and r straight back -- the exact bug PR #6
                          // shipped. Releasing focus here fires the -1.
                          onVisibleChanged: if (!visible && activeFocus)
                                              focus = false

                          // Clamped at zero: two fields handing focus over
                          // directly fire their signals in either order, and
                          // onExpandedModelChanged also resets to 0, so an
                          // unclamped -= could strand the counter negative --
                          // permanently below the `> 0` that blocks the key
                          // catcher. Clamping fails toward blocking.
                          onActiveFocusChanged: root.paramFieldsFocused =
                            Math.max(0, root.paramFieldsFocused +
                                        (activeFocus ? 1 : -1))

                          onEditingFinished: {
                            var parsed = Model.parseParamInput(paramKey, text)
                            if (isNaN(parsed)) {
                              // Garbage reverts rather than being stored, so
                              // apply can never offer to send it.
                              text = Qt.binding(function () {
                                return service.paramEditText(root.expandedEntry,
                                                             paramKey)
                              })
                              return
                            }
                            service.setParamEdit(root.expandedModel, paramKey,
                                                 String(parsed))
                          }

                          Keys.onEscapePressed: function (event) {
                            // Revert and defocus. Does NOT close the panel --
                            // esc inside an editor means "abandon this edit."
                            // PanelKeyCatcher is already blocked while this
                            // field has focus, so this handler is what fires;
                            // event.accepted is set defensively so nothing
                            // above it reinterprets the key regardless.
                            text = Qt.binding(function () {
                              return service.paramEditText(root.expandedEntry,
                                                           paramKey)
                            })
                            focus = false
                            event.accepted = true
                          }
                        }

                        // The caption shares its field's line and absorbs
                        // the leftover width, so it also does the job the
                        // explicit spacer used to do -- keeping the
                        // label/value pair from being stretched apart. It
                        // previously sat on its own line beneath the field,
                        // which cost one line per parameter on top of the
                        // per-model `config` line; inline, the block reads
                        // as a table instead.
                        //
                        // elide rather than wrap: a wrapped caption grows
                        // the row's height and gives back exactly the space
                        // this change reclaims. Captions are therefore
                        // written to fit -- roughly 40 characters at this
                        // panel's width -- and the elide is the backstop for
                        // a theme with a wider font, not the normal case.
                        Text {
                          text: specRow.spec.description
                          color: root.dim
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          Layout.fillWidth: true
                          elide: Text.ElideRight
                        }
                      }
                    }

                    Button {
                      text: "apply"
                      foreground: root.fg
                      tooltipText: "Rewrite this model's parameters"
                      fontFamily: root.fontFamily
                      fontSize: Style.font.caption
                      horizontalPadding: Style.space(6)
                      verticalPadding: Style.space(2)
                      enabled: service.paramDirty(root.expandedEntry) &&
                               service.actionInProgress === ""
                      opacity: enabled ? 1.0 : 0.4
                      onClicked: service.commitParams(root.expandedEntry)
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
