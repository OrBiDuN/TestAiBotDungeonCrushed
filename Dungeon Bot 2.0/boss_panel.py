"""Read-only encounter history and explicit catalog corrections."""
from datetime import datetime
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QTableWidget,
    QTableWidgetItem,QPushButton,QLabel,QInputDialog,QMessageBox,QAbstractItemView)

def stamp(value):
    return datetime.fromtimestamp(value).strftime('%d.%m %H:%M:%S') if value else '—'

class BossPanel(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        self.store=store
        self.setWindowTitle('Боссы — каталог и осады');self.resize(1050,600)
        layout=QVBoxLayout(self);self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.tables=[];self.data=[]
        for title,headers in [('Каталог боссов',['ID','Имя','Очки','Подтверждение','Обнаружений','Последнее появление']),
                              ('Текущие осады',['№','ID осады','Имя','Очки каталога','Статус','Найден','Последнее наблюдение','Источники'])]:
            table=QTableWidget(0,len(headers));table.setHorizontalHeaderLabels(headers)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.tabs.addTab(table,title);self.tables.append(table)
        row=QHBoxLayout();layout.addLayout(row)
        for title,callback in [('Изображение карточки',self.show_image),('Исправить каталог',self.correct),('Обновить',self.refresh)]:
            button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button)
        layout.addWidget(QLabel('История осад сохраняется после прокрутки и перезапуска. UNKNOWN — данных недостаточно.'))
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(2000)
        self.refresh()

    def refresh(self):
        self.data=[self.store.catalog(),self.store.instances()]
        for index,table in enumerate(self.tables):
            selected=table.currentRow();table.setRowCount(len(self.data[index]))
            for i,r in enumerate(self.data[index]):
                if index==0:
                    values=[r['id'],r['canonical_name'],r['reward_points'],
                        'REVIEW' if r['review_required'] else 'VERIFIED' if r['verified'] else 'PENDING',r['encounters'],stamp(r['last_seen_at'])]
                else:
                    values=[r['discovery_order'],r['id'][:10],r['canonical_name'],
                        r['reward_points'] if r['verified'] and not r['review_required'] else None,
                        r['status'],stamp(r['found_at']),stamp(r['last_seen_at']),f"{r['name_source']} / {r['points_source']}"]
                for j,value in enumerate(values):table.setItem(i,j,QTableWidgetItem(str(value) if value is not None else 'UNKNOWN'))
            if selected>=0 and selected<table.rowCount():table.selectRow(selected)
            table.resizeColumnsToContents()

    def selected(self):
        index=self.tabs.currentIndex();row=self.tables[index].currentRow()
        return (index,self.data[index][row]) if 0<=row<len(self.data[index]) else (index,None)

    def show_image(self):
        index,row=self.selected()
        if not row:return
        path=row['source_image_path' if index==0 else 'last_image_path']
        if not path:return
        dialog=QDialog(self);dialog.setWindowTitle('Сохранённое наблюдение — не текущий видеокадр')
        layout=QVBoxLayout(dialog);label=QLabel();label.setPixmap(QPixmap(path).scaled(850,750,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        layout.addWidget(label);dialog.exec()

    def correct(self):
        index,row=self.selected()
        if not row:return
        cid=row['id'] if index==0 else row['catalog_id']
        if not cid:return
        name,ok=QInputDialog.getText(self,'Имя босса','Правильное имя:',text=row['canonical_name'] or '')
        if not ok:return
        points,ok=QInputDialog.getInt(self,'Очки','Подтверждённые очки:',row['reward_points'] or 1,1,2147483647)
        if not ok:return
        try:self.store.correct(cid,name,points)
        except Exception as exc:QMessageBox.warning(self,'Исправление не сохранено',str(exc))
        self.refresh()
