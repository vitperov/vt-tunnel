#!/bin/bash
set -e

PROJ_NAME=vt-tunnel-gui
MODULE_NAME=vt_tunnel_gui
BUILD_DIR=build
ARCH=all
VERSION=0.1.1
CONTROL=control
CHANGELOG=changelog
COPYRIGHT=copyright
MODULE_SRC_DIR=src/$MODULE_NAME
MODULE_INSTALL_DIR=/usr/lib/python3/dist-packages/
DESKTOP_SRC_DIR=desktop
DESKTOP_FILE=$PROJ_NAME.desktop
DESKTOP_INSTALL_DIR=/usr/share/applications/
POLKIT_SRC_DIR=polkit
POLKIT_FILE=org.$PROJ_NAME.policy
POLKIT_INSTALL_DIR=/usr/share/polkit-1/actions/
ROOT_DIR=`pwd`

PACKAGE_DIR=$ROOT_DIR/$BUILD_DIR/$PROJ_NAME
PACKAGE_CTRL_DIR=$PACKAGE_DIR/DEBIAN
PACKAGE_DOC_DIR=$PACKAGE_DIR/usr/share/doc/$PROJ_NAME

rm -rf $PACKAGE_DIR

mkdir -p $PACKAGE_DIR
mkdir -p $PACKAGE_CTRL_DIR
mkdir -p $PACKAGE_DIR/usr/bin
mkdir -p $PACKAGE_DIR/$MODULE_INSTALL_DIR$MODULE_NAME
mkdir -p $PACKAGE_DIR/$DESKTOP_INSTALL_DIR
mkdir -p $PACKAGE_DIR/$POLKIT_INSTALL_DIR
mkdir -p $PACKAGE_DOC_DIR

cp $ROOT_DIR/$CONTROL $PACKAGE_CTRL_DIR/control
cd $PACKAGE_CTRL_DIR/
sed -i "s/NAME/$PROJ_NAME/g" control
sed -i "s/VERSION/$VERSION/g" control

# Launcher script: imports the installed module and runs it.
cat > $PACKAGE_DIR/usr/bin/$PROJ_NAME << 'EOF'
#!/usr/bin/python3
import sys

from vt_tunnel_gui.app import main

sys.exit(main())
EOF
chmod 755 $PACKAGE_DIR/usr/bin/$PROJ_NAME

# Python module: recursive copy so subpackages (views/, models/) ship too;
# bytecode caches are dev leftovers and must not land in the package
cp -r $ROOT_DIR/$MODULE_SRC_DIR/. $PACKAGE_DIR/$MODULE_INSTALL_DIR$MODULE_NAME/
find $PACKAGE_DIR/$MODULE_INSTALL_DIR$MODULE_NAME -type d -name __pycache__ -exec rm -rf {} +
find $PACKAGE_DIR/$MODULE_INSTALL_DIR$MODULE_NAME -type f -name '*.py' -exec chmod 644 {} +

# Desktop entry and polkit policy
cp $ROOT_DIR/$DESKTOP_SRC_DIR/$DESKTOP_FILE $PACKAGE_DIR/$DESKTOP_INSTALL_DIR
chmod 644 $PACKAGE_DIR/$DESKTOP_INSTALL_DIR/$DESKTOP_FILE
cp $ROOT_DIR/$POLKIT_SRC_DIR/$POLKIT_FILE $PACKAGE_DIR/$POLKIT_INSTALL_DIR
chmod 644 $PACKAGE_DIR/$POLKIT_INSTALL_DIR/$POLKIT_FILE

# Documentation
cp $ROOT_DIR/$CHANGELOG $PACKAGE_CTRL_DIR/
gzip -9 -n -f $PACKAGE_CTRL_DIR/changelog
mv $PACKAGE_CTRL_DIR/changelog.gz $PACKAGE_DOC_DIR/changelog.gz

cp $ROOT_DIR/$COPYRIGHT $PACKAGE_DOC_DIR/
chmod 644 $PACKAGE_DOC_DIR/copyright
chmod 644 $PACKAGE_DOC_DIR/changelog.gz

# Standard filesystem permissions for the package tree
find $PACKAGE_DIR -type d -exec chmod 755 {} +

cd $ROOT_DIR/$BUILD_DIR/
fakeroot dpkg-deb -b $PROJ_NAME

mv $PROJ_NAME.deb package-"$PROJ_NAME"_"$VERSION"_"$ARCH".deb

lintian package-"$PROJ_NAME"_"$VERSION"_"$ARCH".deb
