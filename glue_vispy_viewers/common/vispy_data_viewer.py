from __future__ import absolute_import, division, print_function

try:
    from glue.viewers.common.qt.data_viewer import DataViewer
except ImportError:
    from glue.qt.widgets.data_viewer import DataViewer

from glue.core import message as msg
from glue.utils import nonpartial
from glue.core.state import lookup_class_with_patches

from qtpy import PYQT5, QtWidgets

from .vispy_widget import VispyWidgetHelper
from .viewer_options import VispyOptionsWidget
from .toolbar import VispyViewerToolbar
from .state import Vispy3DViewerState


class BaseVispyViewer(DataViewer):

    _toolbar_cls = VispyViewerToolbar
    tools = ['vispy:save', 'vispy:rotate']

    def __init__(self, session, viewer_state=None, parent=None):

        super(BaseVispyViewer, self).__init__(session, parent=parent)

        self.viewer_state = viewer_state or Vispy3DViewerState()

        self._vispy_widget = VispyWidgetHelper(viewer_state=self.viewer_state)
        self.setCentralWidget(self._vispy_widget.canvas.native)

        self._options_widget = VispyOptionsWidget(parent=self, viewer_state=self.viewer_state)

        self.viewer_state.add_callback('clip_data', nonpartial(self._toggle_clip))

        self.status_label = None
        self.client = None

        # If imageio is available, we can add the record icon
        try:
            import imageio  # noqa
        except ImportError:
            pass
        else:
            self.tools.insert(1, 'vispy:record')

    def register_to_hub(self, hub):

        super(BaseVispyViewer, self).register_to_hub(hub)

        def subset_has_data(x):
            return x.sender.data in self._layer_artist_container.layers

        def has_data(x):
            return x.sender in self._layer_artist_container.layers

        hub.subscribe(self, msg.SubsetCreateMessage,
                      handler=self._add_subset,
                      filter=subset_has_data)

        hub.subscribe(self, msg.SubsetUpdateMessage,
                      handler=self._update_subset,
                      filter=subset_has_data)

        hub.subscribe(self, msg.SubsetDeleteMessage,
                      handler=self._remove_subset,
                      filter=subset_has_data)

        hub.subscribe(self, msg.DataUpdateMessage,
                      handler=self.update_window_title,
                      filter=has_data)

        hub.subscribe(self, msg.NumericalDataChangedMessage,
                      handler=self._numerical_data_changed,
                      filter=has_data)

        hub.subscribe(self, msg.ComponentsChangedMessage,
                      handler=self._update_data,
                      filter=has_data)

        def is_appearance_settings(msg):
            return ('BACKGROUND_COLOR' in msg.settings or
                    'FOREGROUND_COLOR' in msg.settings)

        hub.subscribe(self, msg.SettingsChangeMessage,
                      handler=self._update_appearance_from_settings,
                      filter=is_appearance_settings)

    def unregister(self, hub):
        super(BaseVispyViewer, self).unregister(hub)
        hub.unsubscribe_all(self)

    def _update_appearance_from_settings(self, message):
        self._vispy_widget._update_appearance_from_settings()

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        self._data = data

    # instance by object viewers later
    def add_data(self, data):
        return True

    def _add_subset(self, message):
        pass

    def _update_subset(self, message):
        if message.subset in self._layer_artist_container:
            for layer_artist in self._layer_artist_container[message.subset]:
                layer_artist._update_data()
            self._vispy_widget.canvas.update()

    def _remove_subset(self, message):
        if message.subset in self._layer_artist_container:
            self._layer_artist_container.pop(message.subset)
            self._vispy_widget.canvas.update()

    def _update_data(self, message):
        if message.data in self._layer_artist_container:
            for layer_artist in self._layer_artist_container[message.data]:
                layer_artist._update_data()

    def _numerical_data_changed(self, message):
        for layer_artist in self._layer_artist_container:
            layer_artist._update_data()

    def _redraw(self):
        self._vispy_widget.canvas.render()

    def update_window_title(self, *args):
        pass

    def options_widget(self):
        return self._options_widget

    @property
    def window_title(self):
        return self.LABEL

    def __gluestate__(self, context):
        return dict(state=self.viewer_state.__gluestate__(context),
                    session=context.id(self._session),
                    size=self.viewer_size,
                    pos=self.position,
                    layers=list(map(context.do, self.layers)))

    @classmethod
    def __setgluestate__(cls, rec, context):

        session = context.object(rec['session'])
        viewer = cls(session)
        viewer.register_to_hub(session.hub)
        viewer.viewer_size = rec['size']
        x, y = rec['pos']
        viewer.move(x=x, y=y)

        viewer_state = Vispy3DViewerState.__setgluestate__(rec['state'], context)
        viewer.viewer_state.update_from_state(viewer_state)

        # Restore layer artists
        for l in rec['layers']:
            cls = lookup_class_with_patches(l.pop('_type'))
            layer_state = context.object(l['state'])
            layer_artist = cls(viewer, layer_state=layer_state)
            viewer._layer_artist_container.append(layer_artist)

        return viewer

    def show_status(self, text):
        if not self.status_label:
            statusbar = self.statusBar()
            self.status_label = QtWidgets.QLabel()
            statusbar.addWidget(self.status_label)
        self.status_label.setText(text)

    def restore_layers(self, layers, context):
        pass

    def _toggle_clip(self):
        for layer_artist in self._layer_artist_container:
            if self.viewer_state.clip_data:
                layer_artist.set_clip(self.viewer_state.clip_limits)
            else:
                layer_artist.set_clip(None)

    if PYQT5:

        def show(self):

            # WORKAROUND:
            # Due to a bug in Qt5, a hidden toolbar in glue causes a grey
            # rectangle to be overlaid on top of the glue window. Therefore
            # we check if the toolbar is hidden, and if so we make it into a
            # floating toolbar temporarily - still hidden, so this will not
            # be noticeable to the user.

            # tbar.setAllowedAreas(Qt.NoToolBarArea)

            from qtpy.QtCore import Qt

            tbar = self._session.application._mode_toolbar
            hidden = tbar.isHidden()

            if hidden:
                original_flags = tbar.windowFlags()
                tbar.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

            super(BaseVispyViewer, self).show()

            if hidden:
                tbar.setWindowFlags(original_flags)
                tbar.hide()
