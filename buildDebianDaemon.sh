#!/bin/bash
#set -x

PROJ_NAME=vt-tunnel
BUILD_DIR=build
SERVICE_NAME=vt-tunnel.service
SERVICE_CFG=vt-tunnel.cfg
INSTALL_DIR=/lib/systemd/system/
CFG_DIR=/etc/systemd/system/
CONTROL=control
CHANGELOG=changelog
COPYRIGHT=copyright
VERSION=0.1.1
ROOT_DIR=`pwd`

ARCH=$1

PACKAGE_DIR=$ROOT_DIR/$BUILD_DIR/package-"$ARCH"/$PROJ_NAME
PACKAGE_CTRL_DIR=$PACKAGE_DIR/DEBIAN
PACKAGE_DOC_DIR=$PACKAGE_DIR/usr/share/doc/$PROJ_NAME

#echo PackageDIR=$PACKAGE_DIR
#echo InstallDIR=$PACKAGE_DIR/$INSTALL_DIR

chmod -R 777 $PACKAGE_DIR
rm -rf $PACKAGE_DIR

mkdir -p $PACKAGE_CTRL_DIR
mkdir -p $PACKAGE_DIR/$CFG_DIR
mkdir -p $PACKAGE_DIR/$INSTALL_DIR
mkdir -p $PACKAGE_DOC_DIR

cp $ROOT_DIR/$CONTROL $PACKAGE_CTRL_DIR/control
cd $PACKAGE_CTRL_DIR/
sed -i "s/NAME/$PROJ_NAME/g" control
sed -i "s/VERSION/$VERSION/g" control
sed -i "s/ARCH/$ARCH/g" control

cp $ROOT_DIR/$SERVICE_CFG $PACKAGE_DIR/$CFG_DIR
cp $ROOT_DIR/$SERVICE_NAME $PACKAGE_DIR/$INSTALL_DIR

chmod 644 $PACKAGE_DIR/$CFG_DIR/$SERVICE_CFG
chmod 644 $PACKAGE_DIR/$INSTALL_DIR/$SERVICE_NAME

cp $ROOT_DIR/$CHANGELOG $PACKAGE_CTRL_DIR/
gzip -9 -n -f $PACKAGE_CTRL_DIR/changelog
mv $PACKAGE_CTRL_DIR/changelog.gz $PACKAGE_DOC_DIR/changelog.gz

cp $ROOT_DIR/$COPYRIGHT $PACKAGE_DOC_DIR/

echo "${CFG_DIR}${SERVICE_CFG}" > $PACKAGE_CTRL_DIR/conffiles
#echo "sudo systemctl daemon-reload" > $PACKAGE_CTRL_DIR/triggers
#echo "sudo systemctl start $SERVICE_NAME" >> $PACKAGE_CTRL_DIR/triggers

cd $ROOT_DIR/$BUILD_DIR/package-"$ARCH"/
fakeroot dpkg-deb -b $PROJ_NAME

#mkdir -p $PACKAGE_DEST_DIR
mv $PROJ_NAME.deb package-"$PROJ_NAME"_"$VERSION"_"$ARCH".deb

lintian package-"$PROJ_NAME"_"$VERSION"_"$ARCH".deb
