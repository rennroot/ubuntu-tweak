#!/usr/bin/python

# Ubuntu Tweak - PyGTK based desktop configure tool
#
# Copyright (C) 2007-2008 TualatriX <tualatrix@gmail.com>
#
# Ubuntu Tweak is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Ubuntu Tweak is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ubuntu Tweak; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA

import os
import gtk
import urllib
import urllib2
import gettext
import gobject
import pango

from common.consts import *
from common.utils import get_icon_with_file
from common.gui import GuiWorker
from common.appdata import APPS, CATES_DATA
from common.widgets import TweakPage
from common.widgets.dialogs import ErrorDialog, InfoDialog, QuestionDialog
from common.widgets.utils import ProcessDialog
from common.network.parser import Parser
from common.appdata import get_app_logo, get_app_describ
from common.config import TweakSettings
from filetype import CateView
from xdg.DesktopEntry import DesktopEntry

try:
    from common.package import package_worker, PackageInfo
    DISABLE = False
except ImportError:
    DISABLE = True

DESKTOP_DIR = '/usr/share/app-install/desktop/'
ICON_DIR = os.path.join(DATA_DIR, 'applogos')
REMOTE_APP_DATA = os.path.expanduser('~/.ubuntu-tweak/apps/data/apps.json')
REMOTE_CATE_DATA = os.path.expanduser('~/.ubuntu-tweak/apps/data/cates.json')
REMOTE_DATA_DIR = os.path.expanduser('~/.ubuntu-tweak/apps/data')
REMOTE_LOGO_DIR = os.path.expanduser('~/.ubuntu-tweak/apps/logos')

(
    COLUMN_INSTALLED,
    COLUMN_ICON,
    COLUMN_PKG,
    COLUMN_NAME,
    COLUMN_DESC,
    COLUMN_DISPLAY,
    COLUMN_CATE,
    COLUMN_TYPE,
) = range(8)

(
    CATE_ID,
    CATE_ICON,
    CATE_NAME,
) = range(3)

class CategoryView(gtk.TreeView):
    def __init__(self):
        gtk.TreeView.__init__(self)

        self.app_cate_parser = Parser(REMOTE_CATE_DATA, 'name')
        self.app_logo_handler = LogoHandler(REMOTE_LOGO_DIR)

        self.set_headers_visible(False)
        self.set_rules_hint(True)
        self.model = self.__create_model()
        self.set_model(self.model)
        self.__add_columns()
        self.update_model()

        selection = self.get_selection()
        selection.select_iter(self.model.get_iter_first())

    def __create_model(self):
        '''The model is icon, title and the list reference'''
        model = gtk.ListStore(
                    gobject.TYPE_INT,
                    gtk.gdk.Pixbuf,
                    gobject.TYPE_STRING)
        
        return model

    def __add_columns(self):
        column = gtk.TreeViewColumn(_('Categories'))

        renderer = gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.set_attributes(renderer, pixbuf=CATE_ICON)

        renderer = gtk.CellRendererText()
        column.pack_start(renderer, True)
        column.set_sort_column_id(CATE_NAME)
        column.set_attributes(renderer, text=CATE_NAME)

        self.append_column(column)

    def update_model(self):
        self.model.clear()

        iter = self.model.append()
        self.model.set(iter, 
                CATE_ID, 0,
                CATE_ICON, get_icon_with_file(os.path.join(DATA_DIR, 'appcates', 'all.png'), 16),
                CATE_NAME, _('All Categories'))

        for item in self.get_cate_items():
            iter = self.model.append()
            id, name, icon = self.parse_cate_item(item)
            self.model.set(iter, 
                    CATE_ID, id,
                    CATE_ICON, icon,
                    CATE_NAME, name)

    def get_cate_items(self):
        if self.use_remote_data():
            return self.app_cate_parser.items()
        else:
            return CATES_DATA

    def parse_cate_item(self, item):
        '''
        If item[1] == tuple, so it's local data, or the remote data
        '''
        if type(item) == list:
            id = item[0]
            name = item[1]
            pixbuf = gtk.gdk.pixbuf_new_from_file(os.path.join(DATA_DIR, 'appcates', item[2]))
        elif type(item) == tuple:
            catedata = item[1]
            id = catedata['id']
            name = catedata['name']
            pixbuf = self.get_cate_logo(catedata['name'], catedata['logo'])

        return id, name, pixbuf

    def get_cate_logo(self, pkgname, url=None):
        if url and not self.app_logo_handler.is_exists(pkgname):
            self.app_logo_handler.save_logo(pkgname, url)

        if self.app_logo_handler.is_exists(pkgname):
            return self.app_logo_handler.get_logo(pkgname)
        else:
            return get_app_logo(pkgname, 16)

    def use_remote_data(self):
        return self.app_cate_parser.is_available and TweakSettings.get_use_remote_data()

class AppView(gtk.TreeView):
    __gsignals__ = {
        'changed': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, (gobject.TYPE_INT,))
    }

    def __init__(self):
        gtk.TreeView.__init__(self)

        self.to_add = []
        self.to_rm = []
        self.filter = None

        model = self.__create_model()
        self.__add_columns()
        self.set_model(model)

        self.set_rules_hint(True)
        self.set_search_column(COLUMN_NAME)

        self.show_all()

    def __create_model(self):
        model = gtk.ListStore(
                        gobject.TYPE_BOOLEAN,
                        gtk.gdk.Pixbuf,
                        gobject.TYPE_STRING,
                        gobject.TYPE_STRING,
                        gobject.TYPE_STRING,
                        gobject.TYPE_STRING,
                        gobject.TYPE_STRING,
                        gobject.TYPE_STRING)

        return model

    def sort_model(self):
        model = self.get_model()
        model.set_sort_column_id(COLUMN_NAME, gtk.SORT_ASCENDING)

    def __add_columns(self):
        renderer = gtk.CellRendererToggle()
        renderer.set_property("xpad", 6)
        renderer.connect('toggled', self.on_install_toggled)

        column = gtk.TreeViewColumn(' ', renderer, active = COLUMN_INSTALLED)
        column.set_cell_data_func(renderer, self.install_column_view_func)
        column.set_sort_column_id(COLUMN_INSTALLED)
        self.append_column(column)

        column = gtk.TreeViewColumn('Applications')
        column.set_sort_column_id(COLUMN_NAME)
        column.set_spacing(5)
        renderer = gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.set_cell_data_func(renderer, self.icon_column_view_func)
        column.set_attributes(renderer, pixbuf = COLUMN_ICON)

        renderer = gtk.CellRendererText()
        renderer.set_property("xpad", 6)
        renderer.set_property("ypad", 6)
        renderer.set_property('ellipsize', pango.ELLIPSIZE_END)
        column.pack_start(renderer, True)
        column.add_attribute(renderer, 'markup', COLUMN_DISPLAY)
        self.append_column(column)

    def install_column_view_func(self, cell_layout, renderer, model, iter):
        package = model.get_value(iter, COLUMN_PKG)
        if package == None:
            renderer.set_property("visible", False)
        else:
            renderer.set_property("visible", True)

    def icon_column_view_func(self, cell_layout, renderer, model, iter):
        icon = model.get_value(iter, COLUMN_ICON)
        if icon == None:
            renderer.set_property("visible", False)
        else:
            renderer.set_property("visible", True)

    def clear_model(self):
        self.get_model().clear()

    def append_app(self, status, pixbuf, pkgname, appname, desc, category, type='app'):
        model = self.get_model()

        model.append((status,
                pixbuf,
                pkgname,
                appname,
                desc,
                '<b>%s</b>\n%s' % (appname, desc),
                category,
                type))

    def append_changed_app(self, status, pixbuf, pkgname, appname, desc, category):
        model = self.get_model()

        model.append((status,
                pixbuf,
                pkgname,
                appname,
                desc,
                '<span foreground="#ffcc00"><b>%s</b>\n%s</span>' % (appname, desc),
                category,
                'app'))

    def append_update(self, status, pkgname, summary):
        model = self.get_model()
        self.to_add.append(pkgname)

        icontheme = gtk.icon_theme_get_default()
        for icon_name in ['application-x-deb', 'package-x-generic', 'package']:
            icon = icontheme.lookup_icon(icon_name, 32, gtk.ICON_LOOKUP_NO_SVG)
            if icon:
                break

        if icon:
            pixbuf = icon.load_icon()
        else:
            pixbuf = icontheme.load_icon(gtk.STOCK_MISSING_IMAGE, 32, 0)

        model.append((status,
                      pixbuf,
                      pkgname,
                      pkgname,
                      summary,
                      '<b>%s</b>\n%s' % (pkgname, summary),
                      None,
                      'update'))

    def update_model(self, apps, cates=None):
        '''apps is a list to iter pkgname,
        cates is a dict to find what the category the pkg is
        '''
        def do_append(is_installed, pixbuf, pkgname, appname, desc, category):
            if pkgname in self.to_add or pkgname in self.to_rm:
                self.append_changed_app(not is_installed,
                        pixbuf,
                        pkgname,
                        appname,
                        desc,
                        category)
            else:
                self.append_app(is_installed,
                        pixbuf,
                        pkgname,
                        appname,
                        desc,
                        category)

        model = self.get_model()

        icon = gtk.icon_theme_get_default()

        for pkgname in apps:
            if cates:
                category = cates[pkgname][0]
            else:
                category = 0

            pixbuf = get_app_logo(pkgname)

            try:
                package = PackageInfo(pkgname)
                is_installed = package.check_installed()
                appname = package.get_name()
                desc = get_app_describ(pkgname)
            except KeyError:
                continue

            if self.filter == None:
                do_append(is_installed, pixbuf, pkgname, appname, desc, category)
            else:
                if self.filter == category:
                    do_append(is_installed, pixbuf, pkgname, appname, desc, category)

    def on_install_toggled(self, cell, path):
        def do_app_changed(model, iter, appname, desc):
                model.set(iter, COLUMN_DISPLAY, '<span style="italic" weight="bold"><b>%s</b>\n%s</span>' % (appname, desc))
        def do_app_unchanged(model, iter, appname, desc):
                model.set(iter, COLUMN_DISPLAY, '<b>%s</b>\n%s' % (appname, desc))

        model = self.get_model()

        iter = model.get_iter((int(path),))
        is_installed = model.get_value(iter, COLUMN_INSTALLED)
        pkgname = model.get_value(iter, COLUMN_PKG)
        appname = model.get_value(iter, COLUMN_NAME)
        desc = model.get_value(iter, COLUMN_DESC)
        type = model.get_value(iter, COLUMN_TYPE)

        if type == 'app':
            is_installed = not is_installed
            if is_installed:
                if pkgname in self.to_rm:
                    self.to_rm.remove(pkgname)
                    do_app_unchanged(model, iter, appname, desc)
                else:
                    self.to_add.append(pkgname)
                    do_app_changed(model, iter, appname, desc)
            else:
                if pkgname in self.to_add:
                    self.to_add.remove(pkgname)
                    do_app_unchanged(model, iter, appname, desc)
                else:
                    self.to_rm.append(pkgname)
                    do_app_changed(model, iter, appname, desc)

            model.set(iter, COLUMN_INSTALLED, is_installed)
        else:
            to_installed = is_installed
            to_installed = not to_installed
            if to_installed == True:
                self.to_add.append(pkgname)
            else:
                self.to_add.remove(pkgname)

            model.set(iter, COLUMN_INSTALLED, to_installed)

        self.emit('changed', len(self.to_add) + len(self.to_rm))

    def set_filter(self, filter):
        self.filter = filter

class LogoHandler:
    def __init__(self, dir):
        self.dir = dir
        if not os.path.exists(self.dir):
            os.mkdir(self.dir)

    def save_logo(self, name, url):
        data = urllib.urlopen(url).read()
        f = open(os.path.join(self.dir, '%s.png' % name), 'w')
        f.write(data)
        f.close()

    def get_logo(self, name):
        path = os.path.join(self.dir, '%s.png' % name)

        try:
            pixbuf = gtk.gdk.pixbuf_new_from_file(path)
            if pixbuf.get_width() != 16 or pixbuf.get_height() != 16:
                pixbuf = pixbuf.scale_simple(16, 16, gtk.gdk.INTERP_BILINEAR)
            return pixbuf
        except:
            return gtk.icon_theme_get_default().load_icon(gtk.STOCK_MISSING_IMAGE, 16, 0)

    def is_exists(self, name):
        return os.path.exists(os.path.join(self.dir, '%s.png' % name))

class FetchingMetaDialog(ProcessDialog):
    app_url = 'http://127.0.0.1:8000/app/featured/'
    cate_url = 'http://127.0.0.1:8000/app/category/featured/'

    url_mapping = (
        (app_url, REMOTE_APP_DATA),
        (cate_url, REMOTE_CATE_DATA),
    )

    def __init__(self, parent):
        self.done = False
        self.error = None
        self.user_action = False

        super(FetchingMetaDialog, self).__init__(parent=parent)
        self.set_dialog_lable(_('Fetching online data...'))

    def process_data(self):
        for url, path in self.url_mapping:
            try:
                req = urllib2.Request(url=url)
                #TODO get language from locale
                req.add_header('Accept-Language', 'zh-cn')
                data = urllib2.urlopen(req).read()
                f = open(path, 'w')
                f.write(data)
                f.close()
            except:
                self.error = True
                break

        self.done = True

    def on_timeout(self):
        self.pulse()

        if self.error:
            self.destroy()
        elif not self.done:
            return True
        else:
            self.destroy()

class FetchingDialog(ProcessDialog):
    def __init__(self, parent, caller):
        self.caller = caller
        self.done = False
        self.message = None
        self.user_action = False

        super(FetchingDialog, self).__init__(parent=parent)
        self.set_dialog_lable(_('Fetching online data...'))

    def process_data(self):
        import time
        self.caller.model.clear()
        for item in self.caller.get_items():
            time.sleep(1)

            try:
                pkgname, category, pixbuf, desc, appname, is_installed = self.caller.parse_item(item)
            except IOError:
                self.message = _('Network is error')
                break
            except KeyError:
                continue

            self.caller.model.append((is_installed,
                    pixbuf,
                    pkgname,
                    appname,
                    desc,
                    '<b>%s</b>\n%s' % (appname, desc),
                    category))

            if self.user_action == True:
                break

        self.done = True

    def on_timeout(self):
        self.pulse()

        if not self.done:
            return True
        else:
            self.destroy()

class Installer(TweakPage):
    def __init__(self):
        TweakPage.__init__(self, 
                _('Add/Remove Applications'),
                _('A simple but more effecient method for finding and installing popular packages than the default Add/Remove.'))

        if not os.path.exists(REMOTE_DATA_DIR):
            os.makedirs(REMOTE_DATA_DIR)
        if not os.path.exists(REMOTE_LOGO_DIR):
            os.makedirs(REMOTE_LOGO_DIR)
        self.app_logo_handler = LogoHandler(REMOTE_LOGO_DIR)
        self.app_data_parser = Parser(REMOTE_APP_DATA, 'package')

        self.to_add = []
        self.to_rm = []

        self.package_worker = package_worker

        worker = GuiWorker('installer.glade')
        main_vbox = worker.get_object('main_vbox')
        main_vbox.reparent(self.vbox)

        left_sw = worker.get_object('left_sw')
        self.cateview = CategoryView()
        self.cateview.update_model()
        self.cate_selection = self.cateview.get_selection()
        self.cate_selection.connect('changed', self.on_category_changed)
        left_sw.add(self.cateview)

        right_sw = worker.get_object('right_sw')
        self.treeview = AppView()
        self.treeview.update_model(APPS.keys(), APPS)
        self.treeview.sort_model()
        self.treeview.connect('changed', self.on_app_status_changed)
        right_sw.add(self.treeview)

        self.apply_button = worker.get_object('apply_button')
        self.apply_button.connect('clicked', self.on_apply_clicked)

        self.refresh_button = worker.get_object('refresh_button')
        self.refresh_button.connect('clicked', self.on_refresh_button_clicked)

        self.show_all()

#        gobject.idle_add(self.on_idle_check)

    def on_idle_check(self):
        gtk.gdk.threads_enter()
        if self.check_update():
            dialog = QuestionDialog(_('New application data available, would you like to update?'))
            response = dialog.run()
            dialog.destroy()

            if response == gtk.RESPONSE_YES:
                dialog = FetchingDialog(self.get_toplevel(), self)

                if dialog.run() == gtk.RESPONSE_REJECT:
                    dialog.destroy()

                if dialog.message:
                    ErrorDialog(dialog.message).launch()

        gtk.gdk.threads_leave()

    def check_update(self):
        if os.path.exists(REMOTE_APP_DATA) and os.path.exists(REMOTE_CATE_DATA):
            return True
        else:
            return False

    def on_category_changed(self, widget, data = None):
        model, iter = widget.get_selected()

        if model.get_path(iter)[0] != 0:
            if self.use_remote_data():
                self.treeview.set_filter(model.get_value(iter, CATE_ID))
            else:
                self.treeview.set_filter(model.get_value(iter, CATE_NAME))
        else:
            self.treeview.set_filter(None)

        self.treeview.clear_model()
        self.treeview.update_model(APPS.keys(), APPS)

    def get_app_logo(self, pkgname, url=None):
        if url and not self.app_logo_handler.is_exists(pkgname):
            self.app_logo_handler.save_logo(pkgname, url)

        if self.app_logo_handler.is_exists(pkgname):
            return self.app_logo_handler.get_logo(pkgname)
        else:
            return get_app_logo(pkgname, 16)

    def get_app_describ(self, pkgname):
        try:
            if self.app_data_parser[pkgname].has_key('summary'):
                return self.app_data_parser[pkgname]['summary']
        except:
            pass
        return get_app_describ(pkgname)

    def get_app_meta(self, pkgname):
        '''
        Meta data is App's display name and install status
        Need catch exception: KeyError
        '''
        package = PackageInfo(pkgname)
        return package.get_name(), package.check_installed()

    def get_items(self):
        if self.use_remote_data():
            return self.app_data_parser.items()
        else:
            return APP_DATA

    def parse_item(self, item):
        '''
        If item[1] == tuple, so it's local data, or the remote data
        '''
        if type(item[1]) == tuple:
            pkgname = item[0]
            category = item[-1][0] 

            pixbuf = self.get_app_logo(pkgname)
            desc = self.get_app_describ(pkgname)

            appname, is_installed = self.get_app_meta(pkgname)
        elif type(item[1]) == dict:
            pkgname = item[0]
            pkgdata = item[1]
            appname = pkgdata['name']
            desc = pkgdata['summary']
            category = pkgdata['category']

            pixbuf = self.get_app_logo(pkgname, pkgdata['logo32'])
            appname, is_installed = self.get_app_meta(pkgname)

        return pkgname, category, pixbuf, desc, appname, is_installed

    def update_model(self):
        self.model.clear()

        icon = gtk.icon_theme_get_default()

        for item in self.get_items():
            try:
                pkgname, category, pixbuf, desc, appname, is_installed = self.parse_item(item)
            except KeyError:
                continue

            if self.filter == None:
                if pkgname in self.to_add or pkgname in self.to_rm:
                    self.model.append((not is_installed,
                            pixbuf,
                            pkgname,
                            appname,
                            desc,
                            '<span foreground="#ffcc00"><b>%s</b>\n%s</span>' % (appname, desc),
                            category))
                else:
                    self.model.append((is_installed,
                            pixbuf,
                            pkgname,
                            appname,
                            desc,
                            '<b>%s</b>\n%s' % (appname, desc),
                            category))
            else:
                if self.filter == category:
                    if pkgname in self.to_add or pkgname in self.to_rm:
                        self.model.append((not is_installed,
                                pixbuf,
                                pkgname,
                                appname,
                                desc,
                                '<span foreground="#ffcc00"><b>%s</b>\n%s</span>' % (appname, desc),
                                category))
                    else:
                        self.model.append((is_installed,
                                pixbuf,
                                pkgname,
                                appname,
                                desc,
                                '<b>%s</b>\n%s' % (appname, desc),
                                category))

    def deep_update(self):
        package_worker.update_apt_cache(True)
        self.treeview.clear_model()
        self.treeview.update_model(APPS.keys(), APPS)

    def normal_update(self):
        self.treeview.clear_model()
        self.treeview.update_model(APPS.keys(), APPS)

    def on_apply_clicked(self, widget, data = None):
        to_rm = self.treeview.to_rm
        to_add = self.treeview.to_add
        self.package_worker.perform_action(widget.get_toplevel(), to_add, to_rm)

        package_worker.update_apt_cache(True)

        done = package_worker.get_install_status(to_add, to_rm)

        if done:
            self.apply_button.set_sensitive(False)
            InfoDialog(_('Update Successful!')).launch()
        else:
            ErrorDialog(_('Update Failed!')).launch()

        self.treeview.to_add = []
        self.treeview.to_rm = []
        self.treeview.clear_model()
        self.treeview.update_model(APPS.keys(), APPS)

    def on_refresh_button_clicked(self, widget):
        dialog = FetchingMetaDialog(widget.get_toplevel())
        dialog.run()
        dialog.destroy()

    def on_app_status_changed(self, widget, i):
        if i:
            self.apply_button.set_sensitive(True)
        else:
            self.apply_button.set_sensitive(False)

    def use_remote_data(self):
        return self.app_data_parser.is_available and self.cateview.use_remote_data()

if __name__ == '__main__':
    from utility import Test
    Test(Installer)
