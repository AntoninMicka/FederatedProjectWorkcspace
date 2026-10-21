<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Inventář instalačního kandidáta M0

Snímek 2026-09-09, Ubuntu 26.04 arm64. Data načtena z konkrétního .deb a místní dpkg databáze. Nejde o inventář uživatelova Debian kontejneru ani o právní posouzení releasu.

Balík: `federated-workspace-poc.deb`, 22060 bajtů, SHA-256 `95f8fdb3a8afb94e2d058d40432c155723a3023ebd7d277631d7ba9be1b42fcb`.

## Skutečně přibalené soubory

| Cesta | SHA-256 |
| --- | --- |
| `./usr/bin/federated-workspace-poc` | `47de05dc4cb30983ac14ab60ae376e50d6ede2066eb7541782933a0fc694b850` |
| `./usr/lib/federated-workspace-poc/spikes/__init__.py` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `./usr/lib/federated-workspace-poc/spikes/check_config.py` | `418e8a8d9d721034c887b128324e6b0767ee3a25f4f5e798bf89db1cecaa294f` |
| `./usr/lib/federated-workspace-poc/spikes/check_project.py` | `107454bf99dad8605a5bcc8d21cf4005b30de265e389f56daefc824fbe3eb4a0` |
| `./usr/lib/federated-workspace-poc/spikes/configuration.py` | `4b80b4189aeb779e77df1ac5dbe0a94ccb952d08ca1dbe03b3cce96235e88689` |
| `./usr/lib/federated-workspace-poc/spikes/demo.py` | `9d6c2413dfe680d97a936c0e4bb211310d90b95a027c76407470f0fc15b2acd1` |
| `./usr/lib/federated-workspace-poc/spikes/desktop.py` | `f902a07fa9a3956ebe62c7208a29d73c0500f523e5c9b4f75ec6ff9834249756` |
| `./usr/lib/federated-workspace-poc/spikes/desktop_ui.py` | `6bc327c99ae5eb23203c767b433d733535fb7be01cb1d2871c6956825f9c3cae` |
| `./usr/lib/federated-workspace-poc/spikes/journal.py` | `515f703e38276251948a9d703b738660921c38f574dc9e4fdb46f46bb73a25bb` |
| `./usr/lib/federated-workspace-poc/spikes/local_api.py` | `7ad0c7f95a6ec50d0343eabd75108e5c93a6ebb5d1232beff71a972cb09654e5` |
| `./usr/lib/federated-workspace-poc/spikes/metadata.py` | `f3399b95881c5fa2060ae33295fdc57980222c28e3c48980b9e29bc6bdfa166d` |
| `./usr/lib/federated-workspace-poc/spikes/storage.py` | `5c25ddfdfe8606d7a3d65e6dd5f0e2305c8b791a06cba65c6d284f2e46413d16` |
| `./usr/lib/federated-workspace-poc/spikes/workspace.py` | `7d1d114038b051a92c8c9269be68dd33b17900803b463f21f2e43603302e15e2` |
| `./usr/share/applications/federated-workspace-poc.desktop` | `9448323d645024a8690fe3bc76b31093f9e0640d7fa333ec4ec3e0591b9b5915` |
| `./usr/share/doc/federated-workspace-poc/README` | `a480ce6125d64d9a05fb7b7b47e2e97c577cfc789cc42326cdb2933e8f730f36` |
| `./usr/share/doc/federated-workspace-poc/copyright` | `3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04` |

Vlastní kód, launcher a desktop entry jsou pod projektovou MPL-2.0; přibalený copyright obsahuje LICENSE. Žádný Qt/Python runtime není přibalen. Viz [ADR 0011](0011-debian-package.md).

## Systémové závislosti

Rekurzivní průchod Depends/Pre-Depends od deklarace .deb přes instalované balíky. Alternativy vybírají první instalovaný balík nebo instalovaného poskytovatele virtuálního názvu; nejde o APT solver ani kontrolu verzových podmínek. Recommends/Suggests nejsou zahrnuté. Tabulka zachycuje skutečné místní verze a hash distribučního copyright souboru; texty se nekopírují. Copyright může pokrývat více částí zdrojového balíku, proto jeho seznam licencí není automaticky licencí každé binárky.

| Balík | Verze | Arch | Copyright SHA-256 |
| --- | --- | --- | --- |
| `coreutils` | `9.5-1ubuntu2+0.0.0~ubuntu25` | all | `bda8a4de6138582f106953ce1f57cdfee3b880823080d1a5f656d5b9b2ff977c` |
| `coreutils-from-uutils` | `0.0.0~ubuntu25` | all | `bda8a4de6138582f106953ce1f57cdfee3b880823080d1a5f656d5b9b2ff977c` |
| `debconf` | `1.5.92` | all | `57163c71bd8a5289660892827dd0dfaa7fef47f89deedc9dc6711ced7d0a28d7` |
| `fontconfig` | `2.17.1-3ubuntu1` | arm64 | `b215a61cdd3e62b5b17cc28b1852c78acb3dd38be0fb30706f7efc050dba91db` |
| `fontconfig-config` | `2.17.1-3ubuntu1` | arm64 | `b215a61cdd3e62b5b17cc28b1852c78acb3dd38be0fb30706f7efc050dba91db` |
| `fonts-dejavu-core` | `2.37-8build1` | all | `63d3ba759d12804c5b31a9d5940d855c1820d1f5999e6b0872eb1c7ff045fbc9` |
| `fonts-dejavu-mono` | `2.37-8build1` | all | `63d3ba759d12804c5b31a9d5940d855c1820d1f5999e6b0872eb1c7ff045fbc9` |
| `gcc-16-base` | `16-20260322-1ubuntu1` | arm64 | `d7815dd2364180835891947d96d808878204dea45b8597602a7952332195fbea` |
| `git` | `1:2.53.0-1ubuntu1` | arm64 | `c60bb8fe022a5f6030d7cc8b98afdd2e2fe84d021e8a2f58e49ab32e176c906d` |
| `git-man` | `1:2.53.0-1ubuntu1` | all | `c60bb8fe022a5f6030d7cc8b98afdd2e2fe84d021e8a2f58e49ab32e176c906d` |
| `gnu-coreutils` | `9.7-3ubuntu2.1` | arm64 | `3a63d4b11a7ba4c1c17175072ea28e07b0f80c7bc1ca042b27431fe65a14755b` |
| `libacl1` | `2.3.2-2` | arm64 | `9a2dfb4a5abc7e84be2cc41f1089be665519c9409549296f6c19de57ab1d37c2` |
| `libasound2-data` | `1.2.15.3-1ubuntu1.1` | all | `28558a697dadb5fe41ac66c8c4818ebbb7041adaf034dbf1aed67d428dac921b` |
| `libasound2t64` | `1.2.15.3-1ubuntu1.1` | arm64 | `28558a697dadb5fe41ac66c8c4818ebbb7041adaf034dbf1aed67d428dac921b` |
| `libatomic1` | `16-20260322-1ubuntu1` | arm64 | `d7815dd2364180835891947d96d808878204dea45b8597602a7952332195fbea` |
| `libattr1` | `1:2.5.2-4ubuntu0.1` | arm64 | `0cbec745d85ea775450b2d54fac55277197f429e52d611f72852ed420450620e` |
| `libavahi-client3` | `0.8-18ubuntu1.1` | arm64 | `0afb6364e3cf40288018fcee00d29ea176b67c09389f12417f1977b5d84e6e9f` |
| `libavahi-common-data` | `0.8-18ubuntu1.1` | arm64 | `0afb6364e3cf40288018fcee00d29ea176b67c09389f12417f1977b5d84e6e9f` |
| `libavahi-common3` | `0.8-18ubuntu1.1` | arm64 | `0afb6364e3cf40288018fcee00d29ea176b67c09389f12417f1977b5d84e6e9f` |
| `libb2-1` | `0.98.1-1.1build2` | arm64 | `8ab5efc2b43fee31be3c4ffaa2fed49f22fa050b2b5eb81b4c792c11d964ff0f` |
| `libblkid1` | `2.41.3-3ubuntu2.2` | arm64 | `35a014187eb5d264405a91bda9ec782afdef9df148b657e67b38d07fabba2acf` |
| `libbrotli1` | `1.2.0-3build1` | arm64 | `24a64e5bb83d0960d1835696a1e23c0896ad6055b0ca47c66ab0eb9a766324b1` |
| `libbsd0` | `0.12.2-2build2` | arm64 | `47eaa031b1741a33a93e7cc8909bfe153acaec7ddff12e4dc7377d0e2ec10e91` |
| `libbz2-1.0` | `1.0.8-6ubuntu0.1` | arm64 | `832ed535ff3c3d025a8d2348eb1b697b89addcf2eaadbc17650262040b9145e2` |
| `libc-gconv-modules-extra` | `2.43-2ubuntu2.4` | arm64 | `c31d10900fdb95d1889005145a2205bb75e3bc018d3ec8265b81364901748e09` |
| `libc6` | `2.43-2ubuntu2.4` | arm64 | `c31d10900fdb95d1889005145a2205bb75e3bc018d3ec8265b81364901748e09` |
| `libclang1-21` | `1:21.1.8-6ubuntu1` | arm64 | `b2ed2fd344e8ddbf2e0c83113bd40fa1853438be61a0ff20af5acd187c07cbf6` |
| `libcom-err2` | `1.47.2-3ubuntu4` | arm64 | `2041b5febdc110151ca3372d01b16b85dda1888e33f3f60fce0f59940eed7d19` |
| `libcrypt1` | `1:4.5.1-1` | arm64 | `4d740da7ee838a890f134cf6d0ea85319e75a0b7fbc5728b986931028d69d3a4` |
| `libcups2t64` | `2.4.16-1ubuntu1` | arm64 | `16c9666d50f31e830d56e5dbf31e84e61b8841ae5186d9c8cc02ab6efdf387e1` |
| `libcurl3t64-gnutls` | `8.18.0-1ubuntu2.1` | arm64 | `b36986270d288caa9f7c44876802de7a491139f3903dcb6356707ece08e1df4a` |
| `libdb5.3t64` | `5.3.28+dfsg2-10ubuntu1` | arm64 | `8b53da37d73289d9df7317b3a2dbe16491f1fa9fec8b77b86d69704b40ce2c26` |
| `libdbus-1-3` | `1.16.2-2ubuntu4` | arm64 | `f5fd0bfcceb21f4c23a517368abcbfe8a4c1cfb3b521757b50fae4898840fe35` |
| `libdeflate0` | `1.23-2ubuntu1` | arm64 | `b08d3438a0eadaee3103fba087a3e0f639506388ed71e7e2dfbb3e3484e9742c` |
| `libdouble-conversion3` | `3.4.0-1` | arm64 | `1cc0b36cdfe5a674e11cb9907a88291c7602d3805bddd334cc07d57231a0cd00` |
| `libdrm-amdgpu1` | `2.4.131-1` | arm64 | `90df8ca02b0e0f21eebd8e58585345a8a5cd97bd46ad6faa577dc8d07a67aeaa` |
| `libdrm-common` | `2.4.131-1` | all | `90df8ca02b0e0f21eebd8e58585345a8a5cd97bd46ad6faa577dc8d07a67aeaa` |
| `libdrm2` | `2.4.131-1` | arm64 | `90df8ca02b0e0f21eebd8e58585345a8a5cd97bd46ad6faa577dc8d07a67aeaa` |
| `libduktape207` | `2.7.0+tests-0ubuntu4` | arm64 | `ffc72ca2383e76328250b48c18a2c87d551174db0334fee34ca895eae5e1bf6b` |
| `libedit2` | `3.1-20251016-1` | arm64 | `2b53671050f6319be6fcdcafa434e8ccb8af629359b4afc83185867204f3927d` |
| `libegl-mesa0` | `26.0.8-1ubuntu0.3` | arm64 | `6814e1f8e3f030aa74ee8cb9f357fad706631d68d59adcd7192bc96e05199688` |
| `libegl1` | `1.7.0-3` | arm64 | `c47158ee5545d1affd53cf78230afa7b7f0187d61545ab16bb246a475349ef1a` |
| `libelf1t64` | `0.194-4` | arm64 | `2409860c86675ab33f8ad22480608faf849cbc2559d6478f708c23c508a1dbf2` |
| `liberror-perl` | `0.17030-1` | all | `00cf0a4e06977494cbcbe5be1d53d3677ace21a9cdb10a81933b79d067f32e3e` |
| `libevdev2` | `1.13.6+dfsg-1` | arm64 | `15aa26dcc332628ba95d32b7d7a6846718256cd0c91f72b5885e1a6ab2650498` |
| `libexpat1` | `2.7.4-1` | arm64 | `60919fe1a156395ff14511bb6ff79756c50ade2fff59ac60c9bae1d8a7fe6292` |
| `libffi8` | `3.5.2-4` | arm64 | `25ee86cfccc2b7eb9a156a127f1e1b38c46c231f516ff201912223eaf62ee186` |
| `libfontconfig1` | `2.17.1-3ubuntu1` | arm64 | `b215a61cdd3e62b5b17cc28b1852c78acb3dd38be0fb30706f7efc050dba91db` |
| `libfreetype6` | `2.14.2+dfsg-1ubuntu0.1` | arm64 | `8951319d2cbc54c13f091eaedff603f717026e5bf7788902ccd635a094d7a561` |
| `libgbm1` | `26.0.8-1ubuntu0.3` | arm64 | `6814e1f8e3f030aa74ee8cb9f357fad706631d68d59adcd7192bc96e05199688` |
| `libgcc-s1` | `16-20260322-1ubuntu1` | arm64 | `d7815dd2364180835891947d96d808878204dea45b8597602a7952332195fbea` |
| `libgcrypt20` | `1.12.0-2ubuntu1.1` | arm64 | `7d0898872a373d51cf511aaa99671f47c5b76594b9cb5019e1684da90da8345f` |
| `libgdbm-compat4t64` | `1.26-1build1` | arm64 | `c68f7e6c9b84dd360916a21c951a11829cc55b8793d66094dbfc39eba1618696` |
| `libgdbm6t64` | `1.26-1build1` | arm64 | `c68f7e6c9b84dd360916a21c951a11829cc55b8793d66094dbfc39eba1618696` |
| `libgl1` | `1.7.0-3` | arm64 | `c47158ee5545d1affd53cf78230afa7b7f0187d61545ab16bb246a475349ef1a` |
| `libgl1-mesa-dri` | `26.0.8-1ubuntu0.3` | arm64 | `6814e1f8e3f030aa74ee8cb9f357fad706631d68d59adcd7192bc96e05199688` |
| `libglib2.0-0t64` | `2.88.0-1` | arm64 | `498035c1e93c9d12306f4ba8f37686c2a527657f8b17969ec6d11c1af87e543d` |
| `libglvnd0` | `1.7.0-3` | arm64 | `c47158ee5545d1affd53cf78230afa7b7f0187d61545ab16bb246a475349ef1a` |
| `libglx-mesa0` | `26.0.8-1ubuntu0.3` | arm64 | `6814e1f8e3f030aa74ee8cb9f357fad706631d68d59adcd7192bc96e05199688` |
| `libglx0` | `1.7.0-3` | arm64 | `c47158ee5545d1affd53cf78230afa7b7f0187d61545ab16bb246a475349ef1a` |
| `libgmp10` | `2:6.3.0+dfsg-5ubuntu2` | arm64 | `7d366aef5ba325150246de1d7820c4c9926cd27ca61a69948492b26cd3b61601` |
| `libgnutls30t64` | `3.8.12-2ubuntu1.1` | arm64 | `b32655aad8bb1530de36933f8702af1e669fabb9bf3e712c533803c7092d77da` |
| `libgomp1` | `16-20260322-1ubuntu1` | arm64 | `d7815dd2364180835891947d96d808878204dea45b8597602a7952332195fbea` |
| `libgpg-error0` | `1.58-2` | arm64 | `20611cb3c317c3665591d6d7aa9ee29b70f89d98044e2796074cae18f806f2ae` |
| `libgraphite2-3` | `1.3.14-11ubuntu1.1` | arm64 | `a33017ba0308c41bdbde4751bff349ab7b26af45fadbb1e3e7ac67c372985572` |
| `libgssapi-krb5-2` | `1.22.1-2ubuntu4.1` | arm64 | `936728f4181718f42951b881c1e8f1386bf6b2723c4fbc533c374d6f42c71816` |
| `libgudev-1.0-0` | `1:238-7build1` | arm64 | `e8208610819fd05fca6ea4776156858bb934e29c408ae9bdac4a8266a53178e3` |
| `libharfbuzz-subset0` | `12.3.2-2` | arm64 | `407e84e766824b0b8ee7e06da15dbf50e924f4adeec1e4748247a07b3dbc3208` |
| `libharfbuzz0b` | `12.3.2-2` | arm64 | `407e84e766824b0b8ee7e06da15dbf50e924f4adeec1e4748247a07b3dbc3208` |
| `libhogweed6t64` | `3.10.2-1` | arm64 | `344396197142cd506468b20029ea5722d507c980129bb3db4af02424ed6f39c6` |
| `libice6` | `2:1.1.1-1build1` | arm64 | `fc16500a74acc2d0a7bb2fa1005956a52551abdce2afe0642a9a8dc2b6af53c6` |
| `libicu78` | `78.2-2ubuntu1` | arm64 | `5bbff5f646ce750ac0a347e7f91793279b7422a1119820b5f75d98879c201c68` |
| `libidn2-0` | `2.3.8-4build1` | arm64 | `a63ceb8fab281177da9a27403f0be7ae69aa6f33bf6f63c455ecc587ca131268` |
| `libinput-bin` | `1.31.1-1ubuntu1.1` | arm64 | `f075af6e7319a471289bc1908aae04e44ba954ea53b11fcf42ee8d5422f40363` |
| `libinput10` | `1.31.1-1ubuntu1.1` | arm64 | `f075af6e7319a471289bc1908aae04e44ba954ea53b11fcf42ee8d5422f40363` |
| `libjbig0` | `2.1-6.1ubuntu3` | arm64 | `89ab20c324a191652e94598f2144a65442faed4f14f77bbd10516130ee20f05a` |
| `libjpeg-turbo8` | `2.1.5-4ubuntu4` | arm64 | `3821184e23385bf2cdc01f56bd999b34036fc3aa03d5135d41680374eb81bf8a` |
| `libjpeg8` | `8c-2ubuntu12` | arm64 | `2120036d2302821582cf29a90de0cc390f96bdb4545d2c7f700d023030f46200` |
| `libk5crypto3` | `1.22.1-2ubuntu4.1` | arm64 | `936728f4181718f42951b881c1e8f1386bf6b2723c4fbc533c374d6f42c71816` |
| `libkeyutils1` | `1.6.3-6ubuntu3` | arm64 | `73f5682b0466f41cea2b9b7f1ff8a8052464f6c09fb29eeac4490512af09bd50` |
| `libkrb5-3` | `1.22.1-2ubuntu4.1` | arm64 | `936728f4181718f42951b881c1e8f1386bf6b2723c4fbc533c374d6f42c71816` |
| `libkrb5support0` | `1.22.1-2ubuntu4.1` | arm64 | `936728f4181718f42951b881c1e8f1386bf6b2723c4fbc533c374d6f42c71816` |
| `liblcms2-2` | `2.17-1ubuntu0.2` | arm64 | `420fd2c72204652c08a48548a0d1002edab3d9b180d3c416578c61f74092f460` |
| `libldap-common` | `2.6.10+dfsg-1ubuntu5` | all | `2656a8ac4f2fda614be8fe6fd7f649665a6ca3abcf19f6ac125e2ff165b60939` |
| `libldap2` | `2.6.10+dfsg-1ubuntu5` | arm64 | `2656a8ac4f2fda614be8fe6fd7f649665a6ca3abcf19f6ac125e2ff165b60939` |
| `liblerc4` | `4.0.0+ds-5ubuntu2` | arm64 | `6e694f6e6063e7b1ffb5f723ce4e696aa015944cf1b4d15e8f3ea7e90417a71d` |
| `libllvm21` | `1:21.1.8-6ubuntu1` | arm64 | `b2ed2fd344e8ddbf2e0c83113bd40fa1853438be61a0ff20af5acd187c07cbf6` |
| `liblzma5` | `5.8.3-1` | arm64 | `a9c3f6e1bf373b54e29704e31afd99f5405a32cbc7897608b0f15e9d544882d4` |
| `libmd0` | `1.1.0-2build4` | arm64 | `4365ef6255ad553fce69dd4bc0e093472c5d0e41b8ea493a545cc926ce171aa6` |
| `libmd4c0` | `0.5.2-2build1` | arm64 | `9d28637a59aabfb177971159ca182f6fc039e3f8fce383a6cfff7b821ececfbf` |
| `libminizip1t64` | `1:1.3.dfsg+really1.3.1-1ubuntu3.1` | arm64 | `9e5b96d63773a5d177ba264254390f792be07e41748ebd94730981c6cac31cc6` |
| `libmount1` | `2.41.3-3ubuntu2.2` | arm64 | `35a014187eb5d264405a91bda9ec782afdef9df148b657e67b38d07fabba2acf` |
| `libmtdev1t64` | `1.1.7-1build1` | arm64 | `b502da9f272701b04af7f80670e381193e5fd86134d73f7a4c67b6375e43d355` |
| `libncursesw6` | `6.6+20251231-1` | arm64 | `f838d6048fbc59356b7e56c207a7cb32dc6bf4adea95514a002596bde8f6e1e7` |
| `libnettle8t64` | `3.10.2-1` | arm64 | `344396197142cd506468b20029ea5722d507c980129bb3db4af02424ed6f39c6` |
| `libnghttp2-14` | `1.68.0-2ubuntu0.2` | arm64 | `a4d7f9d9d350e7f89aa0688cea74838f33147462d68a3542290387101bf4f274` |
| `libnspr4` | `2:4.38.2-1ubuntu1` | arm64 | `3c4fcc131809b2b6993513bfe4cf6f1ede391ec84f1d5ceca78fb75537b22452` |
| `libnss3` | `2:3.120-1ubuntu2.1` | arm64 | `3f450f9453233852b3a469a36a897cc68fb87be3e8b3a5ba64f63a7904528408` |
| `libopengl0` | `1.7.0-3` | arm64 | `c47158ee5545d1affd53cf78230afa7b7f0187d61545ab16bb246a475349ef1a` |
| `libopenjp2-7` | `2.5.4-1ubuntu0.1` | arm64 | `5e73ad1e015c45c2c82a1f1c25cf9737230270f28f995806d7ab82ebfbc3cc01` |
| `libopus0` | `1.6.1-1` | arm64 | `1580efdb9c8b11bc06510021d948c89dfee78c7eb9bd6d1ac5eb3ebdcbd82d29` |
| `libp11-kit0` | `0.26.2-2` | arm64 | `a5611fbad151d1fa0aa484f6c393a5166af33ce9a9783dfb2712d6b87b462b37` |
| `libpcre2-16-0` | `10.46-1build1` | arm64 | `e915cde4251f96ec6af107ecd2e194440a4e69440893b0c982802f8a1e4ae40a` |
| `libpcre2-8-0` | `10.46-1build1` | arm64 | `e915cde4251f96ec6af107ecd2e194440a4e69440893b0c982802f8a1e4ae40a` |
| `libperl5.40` | `5.40.1-7ubuntu0.2` | arm64 | `8adf04cb72ca0719dee8fdb8d711768548d10373905eac21e8a640881c230257` |
| `libpng16-16t64` | `1.6.57-1` | arm64 | `55c6fc6ffe83143f360b83f26b3064fff499120eff31e4f14ebba6d667308352` |
| `libproxy1v5` | `0.5.12-1` | arm64 | `227915a3750b917cebe8664a066ada783881aae7d3029950110d03495ead2b20` |
| `libpsl5t64` | `0.21.2-1.1build2` | arm64 | `bbafb0cf52d34465fc69f5ffd22d724224f6a2f28402c88b045c69d88af06aaf` |
| `libpyside6-py3-6.10` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `libpython3-stdlib` | `3.14.3-0ubuntu2` | arm64 | `5b274dbb44b28a54b795b9471c07ab045054d6b8a86273cb9feb632b6fd2760d` |
| `libpython3.14-minimal` | `3.14.4-1ubuntu0.2` | arm64 | `f1cbf908e1daa8789b389fdcf17811ed36b675d736b39a103591399861350382` |
| `libpython3.14-stdlib` | `3.14.4-1ubuntu0.2` | arm64 | `f1cbf908e1daa8789b389fdcf17811ed36b675d736b39a103591399861350382` |
| `libqt6core6t64` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libqt6dbus6` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libqt6gui6` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libqt6network6` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libqt6opengl6` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libqt6positioning6` | `6.10.2-1` | arm64 | `241a6bfbb67f7eaa3fe58e77c81a210719e83bc812c0c77df77a9aa7f5af1eb3` |
| `libqt6printsupport6` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libqt6qml6` | `6.10.2+dfsg-3` | arm64 | `14da67d32ee6dd71a532a2979097ab83c7ceb7ed13045b29824a78d399842cfe` |
| `libqt6qmlmeta6` | `6.10.2+dfsg-3` | arm64 | `14da67d32ee6dd71a532a2979097ab83c7ceb7ed13045b29824a78d399842cfe` |
| `libqt6qmlmodels6` | `6.10.2+dfsg-3` | arm64 | `14da67d32ee6dd71a532a2979097ab83c7ceb7ed13045b29824a78d399842cfe` |
| `libqt6qmlworkerscript6` | `6.10.2+dfsg-3` | arm64 | `14da67d32ee6dd71a532a2979097ab83c7ceb7ed13045b29824a78d399842cfe` |
| `libqt6quick6` | `6.10.2+dfsg-3` | arm64 | `14da67d32ee6dd71a532a2979097ab83c7ceb7ed13045b29824a78d399842cfe` |
| `libqt6quickwidgets6` | `6.10.2+dfsg-3` | arm64 | `14da67d32ee6dd71a532a2979097ab83c7ceb7ed13045b29824a78d399842cfe` |
| `libqt6webchannel6` | `6.10.2-1` | arm64 | `2713c29bb9c88eb98bb608811b6481467a3405516e682795fcef9513da97bded` |
| `libqt6webengine6-data` | `6.10.2+dfsg-1` | all | `253a7ede05898d6977b34868c4431f84d8ddba18b6049a68f935e3d1c1bdf27d` |
| `libqt6webenginecore6` | `6.10.2+dfsg-1` | arm64 | `253a7ede05898d6977b34868c4431f84d8ddba18b6049a68f935e3d1c1bdf27d` |
| `libqt6webenginecore6-bin` | `6.10.2+dfsg-1` | arm64 | `253a7ede05898d6977b34868c4431f84d8ddba18b6049a68f935e3d1c1bdf27d` |
| `libqt6webenginewidgets6` | `6.10.2+dfsg-1` | arm64 | `253a7ede05898d6977b34868c4431f84d8ddba18b6049a68f935e3d1c1bdf27d` |
| `libqt6widgets6` | `6.10.2+dfsg-7` | arm64 | `9bc6203f2b6fba7a47138f8370afeff96fff8d67c44ee2752ea4b4e02438d961` |
| `libreadline8t64` | `8.3-4` | arm64 | `00e252bd06d79a7b9bf235934aa1e2e475bd949e9cf179cd388608247d68fac7` |
| `librtmp1` | `2.4+20151223.gitfa8646d.1-3` | arm64 | `2aa6df2ec29edf3e26571e89bda27f0c3a3f187cdf08f75dcc6a7ce32d236824` |
| `libsasl2-2` | `2.1.28+dfsg1-9ubuntu3` | arm64 | `ddb128a81d3a140ef5b3574ae000a1a50d0cb9a2ec59917121a155f91b670166` |
| `libsasl2-modules-db` | `2.1.28+dfsg1-9ubuntu3` | arm64 | `ddb128a81d3a140ef5b3574ae000a1a50d0cb9a2ec59917121a155f91b670166` |
| `libselinux1` | `3.9-4build1` | arm64 | `864f1bb189f609075d580b8c4aada16d85a44546884f1687989e1cacc8c56751` |
| `libsensors-config` | `1:3.6.2-2build1` | all | `0b08081a35b0c3324b1729c68ee3de1808350a120d99dee4b2fa7dc2f43ee58d` |
| `libsensors5` | `1:3.6.2-2build1` | arm64 | `0b08081a35b0c3324b1729c68ee3de1808350a120d99dee4b2fa7dc2f43ee58d` |
| `libsharpyuv0` | `1.5.0-0.1build1` | arm64 | `725344c9200f6e6dad88d1ea88add2d673cdf1d8fbc3961bcd2693ab0c26d30d` |
| `libshiboken6-py3-6.10` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `libsm6` | `2:1.2.6-1build1` | arm64 | `333d829128c80619625f7e43a0ff0e79f36812b2b7ba12696eec9b4b42ce729b` |
| `libsnappy1v5` | `1.2.2-2` | arm64 | `6e3b7206a2a68d959274c289922e06bd19788a3d48d3bf74e92db43ee21593e6` |
| `libsqlite3-0` | `3.46.1-9ubuntu0.2` | arm64 | `7b1679aaa97e6e49ec12460eefa85a82b432053bc468dd89dbdb50f2326589f3` |
| `libssh2-1t64` | `1.11.1-1ubuntu0.26.04.4` | arm64 | `fb5d6b7a53710b6ba04e412a016d222a3e56b9d6e1a2572a8ffc2eae05e6acfb` |
| `libssl3t64` | `3.5.5-1ubuntu3.5` | arm64 | `6a7da622fe0637a334d2a8fc470852d2ffb77d9a2b2f930f854e32a41ad6ef35` |
| `libstdc++6` | `16-20260322-1ubuntu1` | arm64 | `d7815dd2364180835891947d96d808878204dea45b8597602a7952332195fbea` |
| `libsystemd0` | `259.5-0ubuntu3.4` | arm64 | `0fff813dc14e7c0a6d2bfba748ed17485fedb768b7fc9702b15261e81cfd357f` |
| `libtasn1-6` | `4.21.0-2` | arm64 | `722a2780f3f3865c8bed997b8a6283eebf302c9fe4a5b2fb5fd221ea9a51a5a6` |
| `libtiff6` | `4.7.0-3ubuntu5` | arm64 | `d73e31b03a0d7a515851601c19fee5792c7db03a312efacae146ddf9c91f86f1` |
| `libtinfo6` | `6.6+20251231-1` | arm64 | `f838d6048fbc59356b7e56c207a7cb32dc6bf4adea95514a002596bde8f6e1e7` |
| `libts0t64` | `1.22-1.1build2` | arm64 | `6b79c5bd34339026d164d59755477be1975cb6c609f1aba6377a106b2544b763` |
| `libudev1` | `259.5-0ubuntu3.4` | arm64 | `0fff813dc14e7c0a6d2bfba748ed17485fedb768b7fc9702b15261e81cfd357f` |
| `libunistring5` | `1.3-2build1` | arm64 | `a585cd2cc2a5fcb8e58f12c7a710a35e06e5b897c59cd5ae4a7d835f0b49eae3` |
| `libuuid1` | `2.41.3-3ubuntu2.2` | arm64 | `35a014187eb5d264405a91bda9ec782afdef9df148b657e67b38d07fabba2acf` |
| `libvulkan1` | `1.4.341.0-1` | arm64 | `c579213e28f67944a7e407816b8a8e1d2d2406b3d820e420aa923807c450dc07` |
| `libwacom-common` | `2.18.0-1` | all | `5026eb61394922e821cfea069fe9740141b1d6abd3ea900e79655ad45ea1cb8a` |
| `libwacom9` | `2.18.0-1` | arm64 | `5026eb61394922e821cfea069fe9740141b1d6abd3ea900e79655ad45ea1cb8a` |
| `libwayland-client0` | `1.24.0-2` | arm64 | `99ade79b69c41bfb14b8a0567e9c0acdd858d6d8ad7d3ca4f9da1cfd000954b1` |
| `libwebp7` | `1.5.0-0.1build1` | arm64 | `725344c9200f6e6dad88d1ea88add2d673cdf1d8fbc3961bcd2693ab0c26d30d` |
| `libwebpdemux2` | `1.5.0-0.1build1` | arm64 | `725344c9200f6e6dad88d1ea88add2d673cdf1d8fbc3961bcd2693ab0c26d30d` |
| `libwebpmux3` | `1.5.0-0.1build1` | arm64 | `725344c9200f6e6dad88d1ea88add2d673cdf1d8fbc3961bcd2693ab0c26d30d` |
| `libx11-6` | `2:1.8.13-1` | arm64 | `0b380a7fd5b2228f26e9585e56f14812efd3350f3df307507d2bc055dfd8de3e` |
| `libx11-data` | `2:1.8.13-1` | all | `0b380a7fd5b2228f26e9585e56f14812efd3350f3df307507d2bc055dfd8de3e` |
| `libx11-xcb1` | `2:1.8.13-1` | arm64 | `0b380a7fd5b2228f26e9585e56f14812efd3350f3df307507d2bc055dfd8de3e` |
| `libxau6` | `1:1.0.11-1build2` | arm64 | `118dd263a7b91c8f21c489f949bf13281dff9e766deea92b829dac4dce66601a` |
| `libxcb-cursor0` | `0.1.6-1` | arm64 | `8ee3b982784137d7e651d37c8c0978983984b0fe93ce2760013b0abbf6652bed` |
| `libxcb-dri3-0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-glx0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-icccm4` | `0.4.2-1build1` | arm64 | `b5b83faabe190515e7a5938aa00441204cd163e24191ef7bcf5e4ac690acd376` |
| `libxcb-image0` | `0.4.0-2build2` | arm64 | `daf2d51e978ec64fc21f59b12d850c2efc907c15eae5c4ba2f3237ce946476de` |
| `libxcb-keysyms1` | `0.4.1-1build1` | arm64 | `cb93f3be4559362c1b8c9484a4a669677f155333456757b9be406dd7d6fa2b01` |
| `libxcb-present0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-randr0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-render-util0` | `0.3.10-1build1` | arm64 | `fc1a08132096d37decac98a8a82e21ee8104e43c434daa2c620d19b55d8b8367` |
| `libxcb-render0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-shape0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-shm0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-sync1` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-util1` | `0.4.1-1build1` | arm64 | `1142dc404c2f6845a5e9a39ee569e670fd629b3a974a03bcd64f84e57e5acd90` |
| `libxcb-xfixes0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-xinput0` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb-xkb1` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcb1` | `1.17.0-2ubuntu1` | arm64 | `4f7cb9db6bf6542f5417e3d674c780d3a5fd12291a54d63054fb576ee0cfae80` |
| `libxcomposite1` | `1:0.4.6-1build1` | arm64 | `e37c7a7e4026343c3e5c13990a6d9a8879194ae3ab26bfe420b34f6f206bf35f` |
| `libxdamage1` | `1:1.1.7-1` | arm64 | `7620eb11cc659b8793cf6fc2f7e1eff23fe819cd1b53f506a502944ecaef6f90` |
| `libxdmcp6` | `1:1.1.5-2` | arm64 | `aceaa93ea2bb08890d7f91987ecf6a03814309470c819c56fe79f7698e45ef53` |
| `libxext6` | `2:1.3.4-1build3` | arm64 | `bc57e445ca1d9fe082c8d54189dd411ff26caa8552c9c63d44ea06a982f32124` |
| `libxfixes3` | `1:6.0.0-2build2` | arm64 | `051ffe073ab38244c504bb379903b4ecda6081fb3d97d0d3dce44bc11712eef2` |
| `libxkbcommon-x11-0` | `1.13.1-1` | arm64 | `5eeaeb1b6e029a0274e1573765bb0bae2926ef96a3679203faa4fd00fdaeaa88` |
| `libxkbcommon0` | `1.13.1-1` | arm64 | `5eeaeb1b6e029a0274e1573765bb0bae2926ef96a3679203faa4fd00fdaeaa88` |
| `libxkbfile1` | `1:1.1.0-1build5` | arm64 | `41044d815bd99a5d1267fdabc79b5041fa83c7134639bb81e84f367cefe68316` |
| `libxml2-16` | `2.15.2+dfsg-0.1ubuntu0.1` | arm64 | `ee746b96cfa5be73c3ea3e4cfb1285e9b315d4c9267f99b2ee9c5d911d9fe3f4` |
| `libxrandr2` | `2:1.5.4-1build1` | arm64 | `6d8e6239cfe9dd25bbeef06dcf0610d802ebbdc8968db87cf5adf00ff98927d4` |
| `libxrender1` | `1:0.9.12-1build1` | arm64 | `ed2a78123a5076b4f11da38cb1ffb85b5cb9fdc26b5746c517b1d7e7a9029704` |
| `libxshmfence1` | `1.3.3-1build1` | arm64 | `6a76b32c9174c0cb9e3d94c323a14d33d6a42bd2a61579b189cbc5addeb94abe` |
| `libxslt1.1` | `1.1.45-0.1` | arm64 | `4b82c8dd6e55001a5921bea1d6db20be5c51e5976d892e870324026c23f37b6f` |
| `libxtst6` | `2:1.2.5-1build1` | arm64 | `304f78731e1e0e78132fbba4e1909c8642878a3b8c4837b36cb2d38891bf2204` |
| `libxxf86vm1` | `1:1.1.4-2` | arm64 | `8cb1cf3789c7fdcb33a9b8487b797ce1cc91205e3e4303b66189fd057b46a321` |
| `libyaml-0-2` | `0.2.5-2build3` | arm64 | `3415b508dee94adcff525a8a2335dca6b9122e2543fd16566e7cfd8ab7713d6b` |
| `libzstd1` | `1.5.7+dfsg-3` | arm64 | `2efe51c80ddc473bc2c91faec49dae645bf7f5a04824528fec816320432da2ae` |
| `lsb-base` | `11.6build1` | all | `5838867827e001081f2a1884f55614df9fbb303bb03de6087220ac0b6f8ea44b` |
| `media-types` | `14.0.0build1` | all | `5ded7c53199b6a1d089b0b7e231d77e5c84081c7156b372b3f11ad9c1c2c5cc7` |
| `mesa-libgallium` | `26.0.8-1ubuntu0.3` | arm64 | `6814e1f8e3f030aa74ee8cb9f357fad706631d68d59adcd7192bc96e05199688` |
| `netbase` | `6.5build1` | all | `795b66147ea5ad692991caa7008ece551fb0fa88b9c53656223bd1518dc58ab2` |
| `openssl-provider-legacy` | `3.5.5-1ubuntu3.5` | arm64 | `6a7da622fe0637a334d2a8fc470852d2ffb77d9a2b2f930f854e32a41ad6ef35` |
| `perl` | `5.40.1-7ubuntu0.2` | arm64 | `8adf04cb72ca0719dee8fdb8d711768548d10373905eac21e8a640881c230257` |
| `perl-base` | `5.40.1-7ubuntu0.2` | arm64 | `8adf04cb72ca0719dee8fdb8d711768548d10373905eac21e8a640881c230257` |
| `perl-modules-5.40` | `5.40.1-7ubuntu0.2` | all | `8adf04cb72ca0719dee8fdb8d711768548d10373905eac21e8a640881c230257` |
| `python3` | `3.14.3-0ubuntu2` | arm64 | `5b274dbb44b28a54b795b9471c07ab045054d6b8a86273cb9feb632b6fd2760d` |
| `python3-minimal` | `3.14.3-0ubuntu2` | arm64 | `5b274dbb44b28a54b795b9471c07ab045054d6b8a86273cb9feb632b6fd2760d` |
| `python3-pyside6.qtcore` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtgui` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtnetwork` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtprintsupport` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtwebchannel` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtwebenginecore` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtwebenginewidgets` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-pyside6.qtwidgets` | `6.10.2-6ubuntu1` | arm64 | `5c08d80593d63f99f900fc18b4c2e4d7e5e3a795a79517fdd1653674bb92d4c5` |
| `python3-yaml` | `6.0.3-1build1` | arm64 | `f7dbbf7598bbd40e0ea8aabec5045466e45564463a75d35ce519e3ea75071f19` |
| `python3.14` | `3.14.4-1ubuntu0.2` | arm64 | `f1cbf908e1daa8789b389fdcf17811ed36b675d736b39a103591399861350382` |
| `python3.14-minimal` | `3.14.4-1ubuntu0.2` | arm64 | `f1cbf908e1daa8789b389fdcf17811ed36b675d736b39a103591399861350382` |
| `readline-common` | `8.3-4` | all | `00e252bd06d79a7b9bf235934aa1e2e475bd949e9cf179cd388608247d68fac7` |
| `rust-coreutils` | `0.8.0-0ubuntu3` | arm64 | `7c87172e05e3b69bf2ab331b5ab692814e0e205cacd41d117d84612c40d9c8cf` |
| `shared-mime-info` | `2.4-5build3` | arm64 | `5145b47d997486e5327091374e807046a32216168b6f2bbf6d1816f60927686c` |
| `sysvinit-utils` | `3.15-5ubuntu1` | arm64 | `53b43fcbd9de018b1c5f288f7c4d01af22f8042e98dd8c8ba091334420151180` |
| `tzdata` | `2026c-0ubuntu0.26.04.1` | all | `6154bb6c9ac34c2ac3ff4217c948fd6b431e3e122a3428d665bebd6f730e9f69` |
| `x11-common` | `1:7.7+26ubuntu1` | all | `2badb73e6e70d0bd2e0b85d39ce18d3c66cfebc3e301720374fa20e6539c947d` |
| `xkb-data` | `2.46-2` | all | `8be5b210e9aef063a19611ce80200862a992130e484d55898cf0181b59ea2962` |
| `zlib1g` | `1:1.3.dfsg+really1.3.1-1ubuntu3.1` | arm64 | `9e5b96d63773a5d177ba264254390f792be07e41748ebd94730981c6cac31cc6` |

Celkem 229 systémových balíků. Copyright cesta je `/usr/share/doc/<balík>/copyright`.
Nerozlišené závislosti: žádné v tomto průchodu.

## Zbývající release kontrola

Před veřejnou distribucí ověřit licenční povinnosti proti konkrétním použitým souborům, dostupnost odpovídajících zdrojů a notices, nahradit maintainer placeholder a zvolit aktualizační kanál. Tento snímek nevydává balík za production-ready. Změna .deb nebo runtime vyžaduje nový snímek; původní hash nelze přenášet na jiné sestavení.
