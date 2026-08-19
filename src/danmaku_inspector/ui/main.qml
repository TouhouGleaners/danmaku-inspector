import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

ApplicationWindow {
    id: root
    visible: true
    width: 960
    height: 640
    minimumWidth: 800
    minimumHeight: 500
    title: "弹幕校验工具"
    color: "#f0f2f5"

    property var selectedPart: null

    // 主内容
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // 标题
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Text {
                text: "弹幕校验工具"
                font.pixelSize: 20
                font.bold: true
                color: "#1a1a1a"
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "导出 CSV"
                flat: true
                enabled: resultView.count > 0 && !backend.isRunning
                onClicked: backend.export_csv()
            }
            Button {
                text: "导出漏发"
                flat: true
                enabled: resultView.count > 0 && !backend.isRunning
                onClicked: backend.export_diff(xmlDirInput.text + "/export", 0.1)
            }
        }

        // 输入区
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: inputLayout.implicitHeight + 32
            radius: 10
            color: "#fff"

            ColumnLayout {
                id: inputLayout
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                RowLayout {
                    spacing: 8
                    Text { text: "BV号"; font.pixelSize: 12; color: "#888"; Layout.preferredWidth: 52 }
                    TextField {
                        id: bvidInput
                        placeholderText: "BV1xxXXXXX"
                        Layout.fillWidth: true
                        enabled: !backend.isRunning
                        background: Rectangle {
                            radius: 6
                            border.color: parent.activeFocus ? "#1976d2" : "#e0e0e0"
                            border.width: parent.activeFocus ? 2 : 1
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                    }
                }

                RowLayout {
                    spacing: 8
                    Text { text: "Cookie"; font.pixelSize: 12; color: "#888"; Layout.preferredWidth: 52 }
                    TextField {
                        id: cookieInput
                        placeholderText: "SESSDATA=xxx"
                        Layout.fillWidth: true
                        enabled: !backend.isRunning
                        background: Rectangle {
                            radius: 6
                            border.color: parent.activeFocus ? "#1976d2" : "#e0e0e0"
                            border.width: parent.activeFocus ? 2 : 1
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                    }
                }

                RowLayout {
                    spacing: 8
                    Text { text: "目录"; font.pixelSize: 12; color: "#888"; Layout.preferredWidth: 52 }
                    TextField {
                        id: xmlDirInput
                        placeholderText: "本地 XML 文件目录"
                        Layout.fillWidth: true
                        enabled: !backend.isRunning
                        background: Rectangle {
                            radius: 6
                            border.color: parent.activeFocus ? "#1976d2" : "#e0e0e0"
                            border.width: parent.activeFocus ? 2 : 1
                            Behavior on border.color { ColorAnimation { duration: 150 } }
                        }
                    }
                }

                RowLayout {
                    Layout.alignment: Qt.AlignRight
                    spacing: 8
                    Button {
                        text: "清空"
                        flat: true
                        enabled: !backend.isRunning
                        onClicked: {
                            bvidInput.text = ""
                            cookieInput.text = ""
                            xmlDirInput.text = ""
                        }
                    }
                    Button {
                        text: backend.isRunning ? "检测中..." : "开始检测"
                        highlighted: !backend.isRunning
                        enabled: !backend.isRunning
                        onClicked: backend.start_inspect(bvidInput.text, cookieInput.text, xmlDirInput.text)

                        background: Rectangle {
                            radius: 6
                            color: parent.down ? "#1565c0" : parent.hovered ? "#1976d2" : "#1976d2"
                            Behavior on color { ColorAnimation { duration: 100 } }
                        }
                    }
                }
            }
        }

        // 进度条
        ProgressBar {
            Layout.fillWidth: true
            visible: backend.isRunning
            indeterminate: true
            height: 3
        }

        // 结果表格
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 10
            color: "#fff"

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // 表头
                Rectangle {
                    Layout.fillWidth: true
                    height: 36
                    color: "#f8f9fa"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16

                        Text { text: "分P"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 50; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "状态"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 70; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "线上"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "应发"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "漏发"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "漏发率"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "错发"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                        Text { text: "操作"; font.pixelSize: 11; font.bold: true; color: "#666"; Layout.preferredWidth: 240; horizontalAlignment: Text.AlignHCenter }
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: "#eee" }

                // 空状态
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: resultView.count === 0 && !backend.isRunning

                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: 16

                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter
                            width: 80
                            height: 80
                            radius: 40
                            color: "#f5f5f5"

                            Text {
                                anchors.centerIn: parent
                                text: "D"
                                font.pixelSize: 32
                                font.bold: true
                                color: "#ccc"

                                SequentialAnimation on opacity {
                                    loops: Animation.Infinite
                                    running: backend.resultModel.rowCount() === 0
                                    NumberAnimation { from: 0.5; to: 1; duration: 2000; easing.type: Easing.InOutQuad }
                                    NumberAnimation { from: 1; to: 0.5; duration: 2000; easing.type: Easing.InOutQuad }
                                }
                            }
                        }

                        Text {
                            text: "暂无检测数据"
                            font.pixelSize: 16
                            font.bold: true
                            color: "#666"
                            Layout.alignment: Qt.AlignHCenter
                        }
                        Text {
                            text: "输入 BV 号和 Cookie 后点击「开始检测」"
                            font.pixelSize: 12
                            color: "#bbb"
                            Layout.alignment: Qt.AlignHCenter
                        }
                    }
                }

                // 骨架屏
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: backend.isRunning && backend.resultModel.rowCount() === 0
                    spacing: 0

                    Repeater {
                        model: 5

                        Rectangle {
                            Layout.fillWidth: true
                            height: 44
                            color: index % 2 === 0 ? "#fff" : "#fafafa"

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 16
                                spacing: 12

                                Repeater {
                                    model: [50, 60, 60, 60, 60, 60, 60, 60]

                                    Rectangle {
                                        width: modelData
                                        height: 16
                                        radius: 4
                                        color: "#eee"

                                        SequentialAnimation on opacity {
                                            loops: Animation.Infinite
                                            NumberAnimation { from: 0.5; to: 1; duration: 1000; easing.type: Easing.InOutQuad }
                                            NumberAnimation { from: 1; to: 0.5; duration: 1000; easing.type: Easing.InOutQuad }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // 数据行
                ListView {
                    id: resultView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: backend.resultModel
                    visible: count > 0

                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }

                    add: Transition {
                        NumberAnimation { properties: "opacity"; from: 0; to: 1; duration: 300 }
                        NumberAnimation { properties: "y"; duration: 300; easing.type: Easing.OutCubic }
                    }

                    delegate: Rectangle {
                        width: resultView.width
                        height: 44
                        color: selectedPart === index ? "#e3f2fd" : (mouseArea.containsMouse ? "#f8f9fa" : (index % 2 === 0 ? "#fff" : "#fafafa"))

                        Behavior on color { ColorAnimation { duration: 100 } }

                        MouseArea {
                            id: mouseArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                selectedPart = index
                                backend.show_part_detail(index)
                            }
                            cursorShape: Qt.PointingHandCursor
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 16
                            anchors.rightMargin: 16

                            Text { text: model.partNum; font.pixelSize: 13; font.bold: true; Layout.preferredWidth: 50; horizontalAlignment: Text.AlignHCenter }
                            Rectangle {
                                Layout.preferredWidth: 70
                                height: 24
                                radius: 12
                                color: model.status === "PASS" ? "#e8f5e9" : model.status === "EXTRA" ? "#ffebee" : "#fff3e0"

                                RowLayout {
                                    anchors.centerIn: parent
                                    spacing: 4
                                    Text {
                                        text: model.status === "PASS" ? "✓" : model.status === "EXTRA" ? "✗" : "⚠"
                                        font.pixelSize: 10
                                        font.bold: true
                                        color: model.status === "PASS" ? "#2e7d32" : model.status === "EXTRA" ? "#c62828" : "#e65100"
                                    }
                                    Text {
                                        text: model.statusText
                                        font.pixelSize: 10
                                        font.bold: true
                                        color: model.status === "PASS" ? "#2e7d32" : model.status === "EXTRA" ? "#c62828" : "#e65100"
                                    }
                                }
                            }
                            Text { text: model.onlineCount; font.pixelSize: 13; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                            Text { text: model.expectedCount; font.pixelSize: 13; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                            Text { text: model.unsentCount; font.pixelSize: 13; font.bold: model.unsentCount > 0; color: model.unsentCount > 0 ? "#e65100" : "#999"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                            Text { text: model.unsentRate; font.pixelSize: 13; color: parseFloat(model.unsentRate) > 10 ? "#c62828" : "#999"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                            Text { text: model.mismatchCount; font.pixelSize: 13; font.bold: model.mismatchCount > 0; color: model.mismatchCount > 0 ? "#c62828" : "#999"; Layout.preferredWidth: 60; horizontalAlignment: Text.AlignHCenter }
                            RowLayout {
                                Layout.preferredWidth: 240
                                spacing: 4
                                Button {
                                    text: "CSV"
                                    font.pixelSize: 10
                                    Layout.preferredWidth: 50
                                    onClicked: backend.export_part_csv(index)
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    background: Rectangle {
                                        radius: 4
                                        color: parent.down ? "#e0e0e0" : parent.hovered ? "#f5f5f5" : "#fff"
                                        border.color: "#ddd"
                                        border.width: 1
                                    }
                                }
                                Button {
                                    text: "E-O"
                                    font.pixelSize: 10
                                    Layout.preferredWidth: 50
                                    onClicked: backend.export_part_diff(index)
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    background: Rectangle {
                                        radius: 4
                                        color: parent.down ? "#e0e0e0" : parent.hovered ? "#f5f5f5" : "#fff"
                                        border.color: "#ddd"
                                        border.width: 1
                                    }
                                }
                                Button {
                                    text: "全量CSV"
                                    font.pixelSize: 10
                                    Layout.preferredWidth: 60
                                    onClicked: backend.export_part_danmaku_csv(index)
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    background: Rectangle {
                                        radius: 4
                                        color: parent.down ? "#e0e0e0" : parent.hovered ? "#f5f5f5" : "#fff"
                                        border.color: "#ddd"
                                        border.width: 1
                                    }
                                }
                                Button {
                                    text: "全量XML"
                                    font.pixelSize: 10
                                    Layout.preferredWidth: 60
                                    onClicked: backend.export_part_danmaku_xml(index)
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    background: Rectangle {
                                        radius: 4
                                        color: parent.down ? "#e0e0e0" : parent.hovered ? "#f5f5f5" : "#fff"
                                        border.color: "#ddd"
                                        border.width: 1
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 状态栏
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Rectangle {
                width: 8; height: 8; radius: 4
                color: backend.isRunning ? "#ff9800" : "#4caf50"

                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    running: backend.isRunning
                    NumberAnimation { from: 1; to: 0.3; duration: 800 }
                    NumberAnimation { from: 0.3; to: 1; duration: 800 }
                }
            }

            Text {
                text: backend.status
                font.pixelSize: 11
                color: backend.isRunning ? "#ff9800" : "#999"
            }

            Item { Layout.fillWidth: true }

            Text {
                text: resultView.count > 0 ? "共 " + resultView.count + " 个分P" : ""
                font.pixelSize: 11
                color: "#999"
            }
        }
    }

    // 详情浮层
    Rectangle {
        id: detailPanel
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 16
        width: 320
        radius: 10
        color: "#fff"
        visible: selectedPart !== null
        z: 10

        x: selectedPart !== null ? parent.width - width - 16 : parent.width
        Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            // 标题
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: selectedPart !== null ? "P" + (selectedPart + 1) + " 详情" : ""
                    font.pixelSize: 16
                    font.bold: true
                    color: "#1a1a1a"
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "✕"
                    flat: true
                    onClicked: selectedPart = null
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: "#f0f0f0" }

            // 统计卡片
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 8
                rowSpacing: 8

                Repeater {
                    model: [
                        { label: "线上弹幕", value: selectedPart !== null ? backend.resultModel.data(backend.resultModel.index(selectedPart, 0), 260) : "0", color: "#333" },
                        { label: "应发弹幕", value: selectedPart !== null ? backend.resultModel.data(backend.resultModel.index(selectedPart, 0), 261) : "0", color: "#333" },
                        { label: "漏发数量", value: selectedPart !== null ? backend.resultModel.data(backend.resultModel.index(selectedPart, 0), 263) : "0", color: "#e65100" },
                        { label: "漏发比例", value: selectedPart !== null ? backend.resultModel.data(backend.resultModel.index(selectedPart, 0), 264) : "0%", color: "#e65100" },
                        { label: "错发数量", value: selectedPart !== null ? backend.resultModel.data(backend.resultModel.index(selectedPart, 0), 265) : "0", color: "#c62828" },
                    ]

                    Rectangle {
                        Layout.fillWidth: true
                        height: 64
                        radius: 8
                        color: "#f8f9fa"

                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: 4
                            Text {
                                text: modelData.value !== undefined ? modelData.value : "0"
                                font.pixelSize: 20
                                font.bold: true
                                color: modelData.color
                                Layout.alignment: Qt.AlignHCenter
                            }
                            Text {
                                text: modelData.label
                                font.pixelSize: 11
                                color: "#999"
                                Layout.alignment: Qt.AlignHCenter
                            }
                        }
                    }
                }
            }

            // 归因标题
            RowLayout {
                Layout.fillWidth: true
                Text { text: "错发归因"; font.pixelSize: 14; font.bold: true; color: "#1a1a1a" }
                Item { Layout.fillWidth: true }
                Text { text: backend.anomalyModel.rowCount() + " 个账号"; font.pixelSize: 12; color: "#999" }
            }

            // 异常列表
            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: backend.anomalyModel

                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 6 }

                delegate: Rectangle {
                    width: parent.width
                    height: 80
                    radius: 8
                    color: "#fff8e1"
                    border.color: "#ffecb3"
                    border.width: 1

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 6

                        RowLayout {
                            Layout.fillWidth: true
                            Text { text: model.midhash; font.pixelSize: 12; font.bold: true; color: "#333" }
                            Item { Layout.fillWidth: true }
                            Rectangle {
                                width: 48; height: 20; radius: 10; color: "#e8f5e9"
                                Text {
                                    anchors.centerIn: parent
                                    text: model.matchRate
                                    font.pixelSize: 10; font.bold: true; color: "#2e7d32"
                                }
                            }
                        }

                        Text { text: "贡献 " + model.extraCount + " 条多余弹幕"; font.pixelSize: 11; color: "#666" }
                        Text { text: "→ 疑似来自 " + model.sourcePart; font.pixelSize: 11; color: "#1976d2"; font.bold: true }
                    }
                }
            }
        }
    }

    // 点击空白处关闭详情
    MouseArea {
        anchors.fill: parent
        z: 5
        visible: selectedPart !== null
        onClicked: selectedPart = null
    }
}
