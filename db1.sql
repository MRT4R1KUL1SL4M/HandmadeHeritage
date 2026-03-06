-- HandmadeHeritageOrganize DB (FIXED ORDER) - MySQL 8+
-- This file fixes foreign key creation order (users/orders before conversations etc).

USE GI_HERITAGE_MARKETPLACE;
SET FOREIGN_KEY_CHECKS=0;

DROP TABLE IF EXISTS admin_profiles;
DROP TABLE IF EXISTS artisans;
DROP TABLE IF EXISTS buyer_addresses;
DROP TABLE IF EXISTS buyer_profiles;
DROP TABLE IF EXISTS certificates;
DROP TABLE IF EXISTS gi_regions;
DROP TABLE IF EXISTS heritage_moods;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS product_approvals;
DROP TABLE IF EXISTS reports;
DROP TABLE IF EXISTS shipment_events;
DROP TABLE IF EXISTS system_config;
DROP TABLE IF EXISTS wishlists;

-- তারপর তোমার script-এর drop গুলা
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversation_reads;
DROP TABLE IF EXISTS review_images;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS payouts;
DROP TABLE IF EXISTS order_tracking;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS shipments;
DROP TABLE IF EXISTS product_images;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS wishlist_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS seller_profiles;
DROP TABLE IF EXISTS user_profiles;
DROP TABLE IF EXISTS admin_logs;
DROP TABLE IF EXISTS password_resets;
DROP TABLE IF EXISTS admins;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS audit_logs;
DROP TABLE IF EXISTS risk_events;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS site_settings;

SET FOREIGN_KEY_CHECKS=1;




-- ------------------------------
-- Table: site_settings
-- ------------------------------
CREATE TABLE `site_settings` (
  `k` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `v` text COLLATE utf8mb4_unicode_ci,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`k`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: users
-- ------------------------------
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(160) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` enum('buyer','seller','admin','superadmin') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'buyer',
  `is_verified` tinyint(1) NOT NULL DEFAULT '0',
  `otp` varchar(12) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` enum('active','blocked') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'active',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  KEY `idx_users_role` (`role`),
  KEY `idx_users_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: risk_events
-- ------------------------------
CREATE TABLE `risk_events` (
  `id` int NOT NULL AUTO_INCREMENT,
  `type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL,
  `severity` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'low',
  `entity_type` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `entity_id` int NOT NULL,
  `note` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_resolved` tinyint(1) NOT NULL DEFAULT '0',
  `resolved_by` int DEFAULT NULL,
  `resolved_at` datetime DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_risk_open` (`is_resolved`,`created_at`),
  KEY `idx_risk_entity` (`entity_type`,`entity_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: audit_logs
-- ------------------------------
CREATE TABLE `audit_logs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `actor_id` int NOT NULL,
  `actor_role` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `action` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL,
  `entity_type` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `entity_id` int NOT NULL,
  `details` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_audit` (`entity_type`,`entity_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: categories
-- ------------------------------
CREATE TABLE `categories` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `slug` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `hero_image` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sort_order` int NOT NULL DEFAULT '0',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  UNIQUE KEY `slug` (`slug`),
  KEY `idx_cat_active_sort` (`is_active`,`sort_order`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: admins
-- ------------------------------
CREATE TABLE `admins` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(190) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'admin',
  `status` varchar(30) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'active',
  `phone` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `address` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `bio` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `photo_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`),
  KEY `idx_admin_email` (`email`),
  KEY `idx_admin_role` (`role`),
  KEY `idx_admin_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: password_resets
-- ------------------------------
CREATE TABLE `password_resets` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `token_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `expires_at` datetime NOT NULL,
  `code_hash` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `code_expires_at` datetime NOT NULL,
  `used_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_pr_user` (`user_id`),
  KEY `idx_pr_hash` (`token_hash`),
  CONSTRAINT `fk_pr_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: admin_logs
-- ------------------------------
CREATE TABLE `admin_logs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `admin_id` int NOT NULL,
  `action` varchar(80) COLLATE utf8mb4_unicode_ci NOT NULL,
  `entity` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `entity_id` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `details` text COLLATE utf8mb4_unicode_ci,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_admin_logs_admin` (`admin_id`,`created_at`),
  CONSTRAINT `fk_admin_logs_admin` FOREIGN KEY (`admin_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: user_profiles
-- ------------------------------
CREATE TABLE `user_profiles` (
  `user_id` int NOT NULL,
  `display_name` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `phone` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `avatar_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `bio` text COLLATE utf8mb4_unicode_ci,
  `city` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `country` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `address_line` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `language_pref` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'en',
  `theme_pref` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'default',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  CONSTRAINT `fk_profile_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: seller_profiles
-- ------------------------------
CREATE TABLE `seller_profiles` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `shop_name` varchar(160) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tagline` varchar(200) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `instagram` varchar(190) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `facebook` varchar(190) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `website` varchar(190) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `shop_logo_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `shop_banner_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payout_method` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payout_account_masked` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payout_account_encrypted` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `nid_number` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tax_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `address` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `nid_front_path` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `nid_back_path` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `selfie_path` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `verification_status` enum('pending','approved','rejected') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `notes` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_id` (`user_id`),
  CONSTRAINT `fk_seller_profile_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: products
-- ------------------------------
CREATE TABLE `products` (
  `id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `seller_id` int DEFAULT NULL,
  `title` varchar(140) COLLATE utf8mb4_unicode_ci NOT NULL,
  `title_bn` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `category_slug` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `description` text COLLATE utf8mb4_unicode_ci,
  `price_usd` decimal(10,2) NOT NULL DEFAULT '0.00',
  `compare_at_usd` decimal(10,2) DEFAULT NULL,
  `stock` int NOT NULL DEFAULT '0',
  `image_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `maker` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rating` decimal(3,2) NOT NULL DEFAULT '0.00',
  `badge` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` enum('draft','active','inactive','archived') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'active',
  `is_featured` tinyint(1) NOT NULL DEFAULT '0',
  `is_trending` tinyint(1) NOT NULL DEFAULT '0',
  `is_flash` tinyint(1) NOT NULL DEFAULT '0',
  `flash_end_at` datetime DEFAULT NULL,
  `dispatch_type` enum('normal','flash','full') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'normal',
  `is_archive` tinyint(1) NOT NULL DEFAULT '0',
  `sold_count` int NOT NULL DEFAULT '0',
  `view_count` int NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_prod_status` (`status`),
  KEY `idx_prod_featured` (`is_featured`,`status`),
  KEY `idx_prod_trending` (`is_trending`,`status`),
  KEY `idx_prod_cat` (`category_slug`),
  KEY `fk_products_seller` (`seller_id`),
  CONSTRAINT `fk_products_category_slug` FOREIGN KEY (`category_slug`) REFERENCES `categories` (`slug`) ON DELETE SET NULL,
  CONSTRAINT `fk_products_seller` FOREIGN KEY (`seller_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------
-- Table structure for table `flash_requests`
-- ------------------------------------------------------

CREATE TABLE `flash_requests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `product_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `seller_id` int NOT NULL,
  `requested_price_usd` decimal(10,2) NOT NULL DEFAULT '0.00',
  `requested_compare_at_usd` decimal(10,2) NOT NULL DEFAULT '0.00',
  `requested_end_at` datetime NOT NULL,
  `status` enum('pending','approved','rejected','cancelled') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `seller_note` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `admin_note` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `reviewed_by` int DEFAULT NULL,
  `reviewed_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_flash_req_status` (`status`,`created_at`),
  KEY `idx_flash_req_product` (`product_id`),
  KEY `idx_flash_req_seller` (`seller_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: orders
-- ------------------------------
CREATE TABLE `orders` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_code` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `buyer_id` int NOT NULL,
  `currency` varchar(8) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'USD',
  `subtotal` decimal(10,2) NOT NULL DEFAULT '0.00',
  `shipping_fee` decimal(10,2) NOT NULL DEFAULT '0.00',
  `tax_fee` decimal(10,2) NOT NULL DEFAULT '0.00',
  `discount` decimal(10,2) NOT NULL DEFAULT '0.00',
  `grand_total` decimal(10,2) NOT NULL DEFAULT '0.00',
  `payment_method` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `trnx_id` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payment_note` text COLLATE utf8mb4_unicode_ci,
  `payment_status` enum('unpaid','submitted','verified','failed','refunded') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'unpaid',
  `status` enum('pending','confirmed','packed','shipped','out_for_delivery','delivered','cancelled','returned','refunded') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `shipping_name` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `shipping_phone` varchar(30) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `shipping_address` text COLLATE utf8mb4_unicode_ci,
  `shipping_region` enum('BD','INTL') COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `gift_message` text COLLATE utf8mb4_unicode_ci,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  `verified_by` int DEFAULT NULL,
  `verified_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `order_code` (`order_code`),
  KEY `idx_orders_buyer` (`buyer_id`,`created_at`),
  KEY `idx_orders_status` (`status`,`created_at`),
  KEY `idx_orders_pay` (`payment_status`,`created_at`),
  KEY `idx_orders_verified` (`verified_at`),
  KEY `fk_orders_verified_by` (`verified_by`),
  CONSTRAINT `fk_orders_buyer` FOREIGN KEY (`buyer_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_orders_verified_by` FOREIGN KEY (`verified_by`) REFERENCES `admins` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: wishlist_items
-- ------------------------------
CREATE TABLE `wishlist_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `product_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_wish_user_product` (`user_id`,`product_id`),
  KEY `idx_wish_user` (`user_id`),
  KEY `fk_wish_product` (`product_id`),
  CONSTRAINT `fk_wish_product` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_wish_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: reviews
-- ------------------------------
CREATE TABLE `reviews` (
  `id` int NOT NULL AUTO_INCREMENT,
  `product_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `buyer_id` int NOT NULL,
  `rating` tinyint NOT NULL,
  `title` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `body` text COLLATE utf8mb4_unicode_ci,
  `is_verified_purchase` tinyint(1) NOT NULL DEFAULT '0',
  `status` enum('pending','approved','rejected','hidden') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_rev_product` (`product_id`,`status`,`created_at`),
  KEY `fk_rev_buyer` (`buyer_id`),
  CONSTRAINT `fk_rev_buyer` FOREIGN KEY (`buyer_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_rev_product` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: product_images
-- ------------------------------
CREATE TABLE `product_images` (
  `id` int NOT NULL AUTO_INCREMENT,
  `product_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `image_url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_primary` tinyint(1) NOT NULL DEFAULT '0',
  `sort_order` int NOT NULL DEFAULT '0',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_pi_product` (`product_id`,`sort_order`),
  CONSTRAINT `fk_pi_product` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: shipments
-- ------------------------------
CREATE TABLE `shipments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `carrier` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'Handmade Heritage Logistics',
  `tracking_code` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `current_status` enum('label_created','picked_up','in_transit','out_for_delivery','delivered','exception','returned') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'label_created',
  `last_update` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `eta_text` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `location_text` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `order_id` (`order_id`),
  UNIQUE KEY `tracking_code` (`tracking_code`),
  CONSTRAINT `fk_ship_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: order_items
-- ------------------------------
CREATE TABLE `order_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `product_id` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  `seller_id` int DEFAULT NULL,
  `title` varchar(140) COLLATE utf8mb4_unicode_ci NOT NULL,
  `image_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `unit_price` decimal(10,2) NOT NULL,
  `qty` int NOT NULL DEFAULT '1',
  `line_total` decimal(10,2) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_oi_order` (`order_id`),
  KEY `idx_oi_product` (`product_id`),
  KEY `idx_oi_seller` (`seller_id`,`order_id`),
  CONSTRAINT `fk_oi_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_oi_product` FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE RESTRICT,
  CONSTRAINT `fk_oi_seller` FOREIGN KEY (`seller_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: order_tracking
-- ------------------------------
CREATE TABLE `order_tracking` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `status` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `note` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `updated_by_role` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `updated_by_id` int NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ot_order` (`order_id`,`created_at`),
  CONSTRAINT `fk_ot_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: payouts
-- ------------------------------
CREATE TABLE `payouts` (
  `id` int NOT NULL AUTO_INCREMENT,
  `order_id` int NOT NULL,
  `seller_id` int DEFAULT NULL,
  `gross_amount` decimal(10,2) NOT NULL DEFAULT '0.00',
  `commission_amount` decimal(10,2) NOT NULL DEFAULT '0.00',
  `net_payable` decimal(10,2) NOT NULL DEFAULT '0.00',
  `status` enum('pending','paid','blocked') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `payout_ref` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payout_method` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payout_account_masked` varchar(80) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payout_proof_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `paid_by` int DEFAULT NULL,
  `paid_at` datetime DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_payout_order_seller` (`order_id`,`seller_id`),
  KEY `idx_payout_status` (`status`,`created_at`),
  KEY `fk_payout_seller` (`seller_id`),
  CONSTRAINT `fk_payout_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_payout_seller` FOREIGN KEY (`seller_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: conversations
-- ------------------------------


DROP TABLE IF EXISTS conversations;

CREATE TABLE `conversations` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `type` VARCHAR(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'order',
  `order_id` INT NULL,
  `buyer_id` INT NOT NULL,
  `seller_id` INT NULL,
  `status` VARCHAR(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'open',
  `priority` VARCHAR(16) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'normal',
  `last_message_at` DATETIME DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

  `order_key` INT GENERATED ALWAYS AS (IFNULL(`order_id`,0)) STORED,
  `seller_key` INT GENERATED ALWAYS AS (IFNULL(`seller_id`,0)) STORED,

  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_conv2` (`type`,`order_key`,`buyer_id`,`seller_key`),
  KEY `idx_conv_buyer` (`buyer_id`,`last_message_at`),
  KEY `idx_conv_seller` (`seller_id`,`last_message_at`),
  KEY `idx_conv_order` (`order_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------
-- Table: review_images
-- ------------------------------
CREATE TABLE `review_images` (
  `id` int NOT NULL AUTO_INCREMENT,
  `review_id` int NOT NULL,
  `image_url` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_rimg_review` (`review_id`),
  CONSTRAINT `fk_rimg_review` FOREIGN KEY (`review_id`) REFERENCES `reviews` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: conversation_reads
-- ------------------------------
CREATE TABLE `conversation_reads` (
  `id` int NOT NULL AUTO_INCREMENT,
  `conversation_id` int NOT NULL,
  `viewer_role` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `viewer_id` int NOT NULL,
  `last_read_message_id` int NOT NULL DEFAULT '0',
  `last_read_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_conv_viewer` (`conversation_id`,`viewer_role`,`viewer_id`),
  KEY `idx_viewer` (`viewer_role`,`viewer_id`),
  KEY `idx_conv` (`conversation_id`),
  CONSTRAINT `fk_cr_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ------------------------------
-- Table: messages
-- ------------------------------
CREATE TABLE `messages` (
  `id` int NOT NULL AUTO_INCREMENT,
  `conversation_id` int NOT NULL,
  `sender_role` enum('buyer','seller','admin') COLLATE utf8mb4_unicode_ci NOT NULL,
  `sender_id` int NOT NULL,
  `message_text` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `status` enum('sent','delivered','seen') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'sent',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg_conv` (`conversation_id`,`id`),
  CONSTRAINT `fk_msg_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS=1;

-- ------------------------------
-- Seed / demo data (dump)
-- ------------------------------
SET FOREIGN_KEY_CHECKS=0;

-- Data: site_settings
INSERT INTO `site_settings` VALUES ('commission_pct','11.0','2026-01-19 21:11:36'),('currency_default','USD',NULL),('site_name','Handmade Heritage',NULL),('support_email','support@handmadeheritage.com',NULL),('topbar_text_bn','অথেনটিক হস্তশিল্প | নিরাপদ পেমেন্ট | বিশ্বজুড়ে ডেলিভারি',NULL),('topbar_text_en','Authentic artisan-made | Secure checkout | Worldwide delivery',NULL);


-- Data: users
INSERT INTO `users` VALUES (1,'Super Admin','superadmin@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','superadmin',1,'000000','active','2026-01-19 15:45:30','2026-01-19 15:45:31'),(2,'Admin One','admin@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','admin',1,'000000','active','2026-01-19 15:45:30','2026-01-19 15:45:31'),(3,'Ayesha Rahman','buyer1@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','buyer',1,'000000','active','2026-01-19 15:45:30','2026-01-19 15:45:31'),(4,'Nafis Ahmed','buyer2@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','buyer',1,'000000','active','2026-01-19 15:45:30','2026-01-19 15:45:31'),(5,'Rina Artisan','seller1@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','seller',1,'000000','active','2026-01-19 15:45:30','2026-01-19 15:45:31'),(6,'Kamal Crafts','seller2@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','seller',1,'000000','active','2026-01-19 15:45:30','2026-01-19 15:45:31');


-- Data: risk_events
INSERT INTO `risk_events` VALUES (1,'high_cancellation_rate','medium','seller',6,'Demo risk: cancellation rate elevated',0,NULL,NULL,'2026-01-19 15:45:31');


-- Data: audit_logs
INSERT INTO `audit_logs` VALUES (1,2,'admin','PAYOUT_MARKED_PENDING','payouts',1,'Demo payout created for seller','2026-01-19 15:45:31'),(2,1,'superadmin','VIEWED_DASHBOARD','system',0,'Superadmin accessed overview','2026-01-19 15:45:31'),(3,1,'admin','order_status_update','order',1,'delivered | ','2026-01-19 15:49:08'),(4,1,'superadmin','settings_update','site_settings',0,'commission_pct=11.0','2026-01-19 21:11:36'),(5,1,'superadmin','admin_role','admin',1,'superadmin','2026-01-19 21:47:32'),(6,1,'superadmin','admin_role','admin',1,'admin','2026-01-19 21:47:33'),(7,1,'superadmin','admin_toggle','admin',1,'disabled','2026-01-19 21:47:35'),(8,1,'superadmin','admin_toggle','admin',1,'active','2026-01-19 21:47:36');


-- Data: categories
INSERT INTO `categories` VALUES (1,'Textiles','textiles','/static/img/cat_textiles.jpg',1,1),(2,'Pottery','pottery','/static/img/cat_pottery.jpg',2,1),(3,'Jewelry','jewelry','/static/img/cat_jewelry.jpg',3,1),(4,'Home Decor','home_decor','/static/img/cat_home_decor.jpg',4,1),(5,'Gifts','gifts','/static/img/cat_gifts.jpg',5,1);


-- Data: admins
INSERT INTO `admins` VALUES (1,'Admin One','admin@handmadeheritage.com','scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8','admin','active','+8801700000099','Dhaka, Bangladesh','Platform operations','/static/uploads/admins/superadmin_1_86cc4529bc48.jpg','2026-01-19 21:45:31','2026-01-19 21:45:30');


-- Data: password_resets
INSERT INTO password_resets
(user_id, token_hash, expires_at, code_hash, code_expires_at, used_at, created_at)
VALUES
(
  3,
  'demo_token_hash_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  '2026-01-20 21:45:31',
  'demo_code_hash_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
  '2026-01-20 21:45:31',
  NULL,
  '2026-01-19 21:45:31'
);



-- Data: admin_logs
INSERT INTO `admin_logs` VALUES (1,2,'ORDER_STATUS_UPDATE','orders','1','Marked order as paid','2026-01-19 15:45:31'),(2,2,'KYC_APPROVED','seller_profiles','6','Seller verified','2026-01-19 15:45:31');


-- Data: user_profiles
INSERT INTO `user_profiles` VALUES (1,'Super Admin','+8801700000001','/static/img/avatars/admin1.png','Platform owner account.','Dhaka','Bangladesh','HQ, Dhaka','en','default','2026-01-19 15:45:30',NULL),(2,'Admin One','+8801700000002','/static/img/avatars/admin2.png','Operations & support admin.','Dhaka','Bangladesh','Banani, Dhaka','en','default','2026-01-19 15:45:30',NULL),(3,'Ayesha','+8801700000003','/static/img/avatars/buyer1.png','Loves handmade gifts & decor.','Chattogram','Bangladesh','Pahartali, Chattogram','bn','default','2026-01-19 15:45:30',NULL),(4,'Nafis','+8801700000004','/static/img/avatars/buyer2.png','Collects pottery & artisan crafts.','Sylhet','Bangladesh','Zindabazar, Sylhet','en','default','2026-01-19 15:45:30',NULL),(5,'Rina Artisan','+8801700000005','/static/img/avatars/seller1.png','Traditional textiles maker.','Rajshahi','Bangladesh','Boalia, Rajshahi','bn','default','2026-01-19 15:45:30',NULL),(6,'Kamal Crafts','+8801700000006','/static/img/avatars/seller2.png','Pottery & home decor crafts.','Khulna','Bangladesh','Sonadanga, Khulna','en','default','2026-01-19 15:45:30',NULL);


-- Data: seller_profiles
INSERT INTO `seller_profiles` VALUES (1,5,'Rina Textiles','Handwoven textiles with heritage','https://instagram.com/rinatextiles','https://facebook.com/rinatextiles','https://rinatextiles.example','/static/img/shops/rina_logo.png','/static/img/shops/rina_banner.jpg','bKash','01XXXXXXXXX',NULL,'NID-RT-0001','TAX-RT-9001','Rajshahi, Bangladesh','/uploads/kyc/rina_nid_front.jpg','/uploads/kyc/rina_nid_back.jpg','/uploads/kyc/rina_selfie.jpg','approved','Verified','2026-01-19 15:45:30',NULL),(2,6,'Kamal Pottery','Modern pottery, timeless feel','https://instagram.com/kamalpottery','https://facebook.com/kamalpottery','https://kamalpottery.example','/static/img/shops/kamal_logo.png','/static/img/shops/kamal_banner.jpg','Nagad','01XXXXXXXXX',NULL,'NID-KP-0002','TAX-KP-9002','Khulna, Bangladesh','/uploads/kyc/kamal_nid_front.jpg','/uploads/kyc/kamal_nid_back.jpg','/uploads/kyc/kamal_selfie.jpg','approved','Verified','2026-01-19 15:45:30',NULL);


-- Data: products
INSERT INTO `products`
(`id`,`seller_id`,`title`,`title_bn`,`category_slug`,`description`,
 `price_usd`,`compare_at_usd`,`stock`,`image_url`,`maker`,`rating`,`badge`,
 `status`,`is_featured`,`is_trending`,`is_flash`,`flash_end_at`,`dispatch_type`,
 `is_archive`,`sold_count`,`view_count`,`created_at`,`updated_at`)
VALUES
('p1',5,'Handwoven Nakshi Textile','হাতের তৈরি নকশি টেক্সটাইল','textiles',
 'Authentic handwoven textile crafted with traditional patterns.',
 24.99,29.99,30,'/uploads/products/p1_main.jpg','Rina Textiles',4.70,'Best Seller',
 'active',1,1,0,NULL,'normal',0,120,980,'2026-01-19 15:45:30',NULL),

('p2',6,'Minimal Ceramic Vase','মিনিমাল সিরামিক ফুলদানি','pottery',
 'A modern ceramic vase with premium glaze finish.',
 18.50,22.00,25,'/uploads/products/p2_main.jpg','Kamal Pottery',4.55,'Trending',
 'active',1,1,0,NULL,'normal',0,80,740,'2026-01-19 15:45:30',NULL),

('p3',5,'Classic Woven Scarf','ক্লাসিক ওভেন স্কার্ফ','textiles',
 'Soft woven scarf designed for everyday elegance.',
 12.99,NULL,60,'/uploads/products/p3_main.jpg','Rina Textiles',4.30,'',
 'active',0,1,0,NULL,'normal',0,55,420,'2026-01-19 15:45:30','2026-01-19 15:45:31'),

('p4',6,'Handcrafted Clay Bowl Set','হাতের তৈরি মাটির বাটি সেট','home_decor',
 'Set of 3 bowls, handcrafted and kiln-fired.',
 21.00,25.00,18,'/uploads/products/p4_main.jpg','Kamal Pottery',4.60,'Limited',
 'active',0,0,0,NULL,'normal',0,35,260,'2026-01-19 15:45:30',NULL),

('p5',5,'Gift Wrap Bundle','উপহার র‍্যাপ বান্ডল','gifts',
 'Premium gift wrap bundle with artisan tags and twine.',
 6.99,8.99,100,'/uploads/products/p5_main.jpg','Handmade Heritage',4.20,'',
 'active',0,0,0,NULL,'normal',0,15,140,'2026-01-19 15:45:30','2026-01-19 15:45:31');


-- Data: orders
INSERT INTO `orders` VALUES (1,'HH-20260116-000001',3,'USD',43.49,5.00,0.00,0.00,48.49,'Card','TRX-AAA-10001','Paid via card gateway.','verified','delivered','Ayesha Rahman','+8801700000003','Pahartali, Chattogram','BD','Please wrap as gift.','2026-01-19 15:45:30','2026-01-19 15:49:08',1,'2026-01-19 21:45:30'),(2,'HH-20260116-000002',4,'USD',18.50,5.00,0.00,2.00,21.50,'bKash','TRX-BBB-10002','Promo applied.','verified','packed','Nafis Ahmed','+8801700000004','Zindabazar, Sylhet','BD','','2026-01-19 15:45:30','2026-01-19 15:45:31',1,'2026-01-19 21:45:30');


-- Data: wishlist_items
INSERT INTO `wishlist_items` VALUES (1,3,'p4','2026-01-19 21:45:31'),(2,4,'p1','2026-01-19 21:45:31');


-- Data: reviews
INSERT INTO `reviews` VALUES (1,'p1',3,5,'Beautiful craftsmanship','The weave quality is excellent and feels premium.',1,'approved','2026-01-19 15:45:31'),(2,'p2',4,5,'Perfect for my living room','Looks clean and modern. Packaging was great.',1,'approved','2026-01-19 15:45:31'),(3,'p3',3,4,'Nice scarf','Soft and comfortable, color matched the photos.',0,'approved','2026-01-19 15:45:31');


-- Data: product_images
INSERT INTO `product_images` VALUES (1,'p1','/uploads/products/p1_main.jpg',1,1,'2026-01-19 15:45:30'),(2,'p1','/uploads/products/p1_2.jpg',0,2,'2026-01-19 15:45:30'),(3,'p1','/uploads/products/p1_3.jpg',0,3,'2026-01-19 15:45:30'),(4,'p2','/uploads/products/p2_main.jpg',1,1,'2026-01-19 15:45:30'),(5,'p2','/uploads/products/p2_2.jpg',0,2,'2026-01-19 15:45:30'),(6,'p3','/uploads/products/p3_main.jpg',1,1,'2026-01-19 15:45:30'),(7,'p3','/uploads/products/p3_2.jpg',0,2,'2026-01-19 15:45:30'),(8,'p4','/uploads/products/p4_main.jpg',1,1,'2026-01-19 15:45:30'),(9,'p5','/uploads/products/p5_main.jpg',1,1,'2026-01-19 15:45:30');


-- Data: shipments
INSERT INTO `shipments` VALUES (1,1,'Handmade Heritage Logistics','HH-TRK-000001','label_created','2026-01-19 15:45:31','ETA 2-4 days','Chattogram Hub'),(2,2,'Handmade Heritage Logistics','HH-TRK-000002','in_transit','2026-01-19 15:45:31','ETA 2-4 days','Sylhet Hub');


-- Data: order_items
INSERT INTO `order_items` VALUES (1,1,'p1',5,'Handwoven Nakshi Textile','/uploads/products/p1_main.jpg',24.99,1,24.99),(2,1,'p2',6,'Minimal Ceramic Vase','/uploads/products/p2_main.jpg',18.50,1,18.50),(3,2,'p2',6,'Minimal Ceramic Vase','/uploads/products/p2_main.jpg',18.50,1,18.50);


-- Data: order_tracking
INSERT INTO `order_tracking` VALUES (1,1,'confirmed','Order confirmed by system','admin',2,'2026-01-19 15:45:31'),(2,1,'packed','Packed and ready for dispatch','seller',6,'2026-01-19 15:45:31'),(3,1,'delivered','','admin',1,'2026-01-19 15:49:08');


-- Data: payouts
INSERT INTO `payouts` VALUES 
(1,1,6,18.50,1.85,16.65,'pending','PAYOUT-DEMO-0001','bKash','01XXXXXXXXX','/uploads/payouts/demo_receipt.jpg',2,NULL,'2026-01-19 15:45:31'),
(2,1,5,24.99,2.50,22.49,'pending',NULL,NULL,'01XXXXXXXXX',NULL,NULL,NULL,'2026-01-19 15:49:08');


-- Data: conversations
INSERT INTO `conversations`
(`id`,`type`,`order_id`,`buyer_id`,`seller_id`,
 `status`,`priority`,`last_message_at`,`created_at`)
VALUES
(1,'order',1,3,6,'open','normal',
 '2026-01-19 21:45:31','2026-01-19 15:45:31'),

(2,'buyer_seller',NULL,3,5,'open','normal',
 '2026-01-20 03:07:29','2026-01-19 21:05:05');


-- Data: review_images
INSERT INTO `review_images` VALUES (1,1,'/uploads/reviews/r1_1.jpg','2026-01-19 15:45:31'),(2,2,'/uploads/reviews/r2_1.jpg','2026-01-19 15:45:31');


-- Data: conversation_reads
INSERT INTO `conversation_reads` VALUES (1,1,'buyer',3,2,'2026-01-20 03:05:15'),(2,1,'seller',6,2,'2026-01-19 21:45:31'),(4,2,'buyer',3,3,'2026-01-20 03:05:17'),(7,2,'seller',5,4,'2026-01-20 03:07:29'),(10,2,'superadmin',1,4,'2026-01-20 04:54:33');


-- Data: messages
INSERT INTO `messages` VALUES (1,1,'buyer',3,'Hi! I just placed this order—can you confirm the delivery timeline?','seen','2026-01-19 15:45:31'),(2,1,'seller',6,'Sure! I will pack it today and share the tracking once shipped.','sent','2026-01-19 15:45:31'),(3,2,'buyer',3,'Hi','sent','2026-01-19 21:05:13'),(4,2,'seller',5,'Hello','sent','2026-01-19 21:07:29');

-- ------------------------------
-- Extensions / extra demo pack / GI / Homepage CMS
-- ------------------------------
-- ============================================================
-- DEMO DATA PACK (Ledger/Risk/Support)
SET FOREIGN_KEY_CHECKS=0;
-- Adds at least 5 rows for payouts (ledger), orders/order_items (risk),
-- and support conversations/messages (support inbox).
-- Safe to run after import (uses INSERT IGNORE with high IDs).
-- ============================================================

-- Use the same password hash as the existing demo users (so you can login easily if needed)
SET @DEMO_HASH := 'scrypt:32768:8:1$0sqEBG9cey0y8LOt$8628224895a2e773b0fccb30d7691fbce7293fac372fa2a84a090aae3b3cb8963b08d81d0f3d48ab8da608fcef1080cab83224a860e1121beb8002fb2c1e51a8';

-- --------------------------
-- Extra demo users
-- --------------------------
INSERT IGNORE INTO users
(id, name, email, password, role, otp, status, created_at, updated_at)
VALUES
(7,'Sumi Boutique','seller3@handmadeheritage.com',@DEMO_HASH,'seller','000000','active','2026-01-20 00:00:00','2026-01-20 00:00:00'),
(8,'Hasan Leather','seller4@handmadeheritage.com',@DEMO_HASH,'seller','000000','active','2026-01-20 00:00:00','2026-01-20 00:00:00'),
(9,'Maya Jewelry','seller5@handmadeheritage.com',@DEMO_HASH,'seller','000000','active','2026-01-20 00:00:00','2026-01-20 00:00:00'),
(10,'Buyer Three','buyer3@handmadeheritage.com',@DEMO_HASH,'buyer','000000','active','2026-01-20 00:00:00','2026-01-20 00:00:00'),
(11,'Buyer Four','buyer4@handmadeheritage.com',@DEMO_HASH,'buyer','000000','active','2026-01-20 00:00:00','2026-01-20 00:00:00'),
(12,'Buyer Five','buyer5@handmadeheritage.com',@DEMO_HASH,'buyer','000000','active','2026-01-20 00:00:00','2026-01-20 00:00:00');

-- --------------------------
-- Seller payout profiles (ensure at least 5)
-- --------------------------
INSERT IGNORE INTO `seller_profiles` (
  `id`,`user_id`,`shop_name`,`tagline`,`instagram`,`facebook`,`website`,
  `shop_logo_url`,`shop_banner_url`,`payout_method`,`payout_account_masked`,
  `nid_number`,`tax_id`,`address`,`nid_front_path`,`nid_back_path`,`selfie_path`,
  `verification_status`,`notes`,`created_at`,`updated_at`
) VALUES
(3,7,'Sumi Boutique','Handmade boutique items','https://instagram.com/sumiboutique',NULL,NULL,NULL,NULL,'bKash','01XXXXXXXXX','NID-SB-0003','TAX-SB-9003','Dhaka, Bangladesh',NULL,NULL,NULL,'pending','KYC not submitted','2026-01-20 00:05:00',NULL),
(4,8,'Hasan Leather','Leather crafts & wallets','https://instagram.com/hasanleather',NULL,NULL,NULL,NULL,'Nagad','01XXXXXXXXX','NID-HL-0004','TAX-HL-9004','Chattogram, Bangladesh',NULL,NULL,NULL,'rejected','Resubmit documents','2026-01-20 00:06:00',NULL),
(5,9,'Maya Jewelry','Silver jewelry & gifts','https://instagram.com/mayajewelry',NULL,NULL,NULL,NULL,'Bank','****-****-****-8899','NID-MJ-0005','TAX-MJ-9005','Sylhet, Bangladesh',NULL,NULL,NULL,'pending','Under review','2026-01-20 00:07:00',NULL);

-- --------------------------
-- Orders (risk signals need >= 5 rows)
--  - Duplicate trnx_id (dup_trx)
--  - Cancel-heavy seller (high_cancel_sellers)
--  - Refund ratio seller (high_refund_sellers)
-- --------------------------
INSERT IGNORE INTO `orders` (
  `id`,`order_code`,`buyer_id`,`currency`,`subtotal`,`shipping_fee`,`tax_fee`,`discount`,`grand_total`,
  `payment_method`,`trnx_id`,`payment_note`,`payment_status`,`status`,
  `shipping_name`,`shipping_phone`,`shipping_address`,`shipping_region`,`gift_message`,
  `created_at`,`updated_at`,`verified_by`,`verified_at`
) VALUES
(3,'HH-20260120-000003',10,'USD',30.00,5.00,0.00,0.00,35.00,'bKash','TRX-DUP-999','Demo duplicate trx','verified','delivered','Buyer Three','+8801700000010','Dhaka','BD','', '2026-01-20 01:00:00',NULL,1,'2026-01-20 01:10:00'),
(4,'HH-20260120-000004',11,'USD',22.00,5.00,0.00,0.00,27.00,'bKash','TRX-DUP-999','Demo duplicate trx','verified','packed','Buyer Four','+8801700000011','Dhaka','BD','', '2026-01-20 01:05:00',NULL,1,'2026-01-20 01:12:00'),
(5,'HH-20260120-000005',10,'USD',15.00,5.00,0.00,0.00,20.00,'Card','TRX-CAN-20001','Cancel demo','verified','cancelled','Buyer Three','+8801700000010','Dhaka','BD','', '2026-01-20 02:00:00',NULL,1,'2026-01-20 02:10:00'),
(6,'HH-20260120-000006',11,'USD',16.00,5.00,0.00,0.00,21.00,'Card','TRX-CAN-20002','Cancel demo','verified','cancelled','Buyer Four','+8801700000011','Dhaka','BD','', '2026-01-20 02:05:00',NULL,1,'2026-01-20 02:12:00'),
(7,'HH-20260120-000007',12,'USD',17.00,5.00,0.00,0.00,22.00,'Card','TRX-CAN-20003','Cancel demo','verified','cancelled','Buyer Five','+8801700000012','Dhaka','BD','', '2026-01-20 02:10:00',NULL,1,'2026-01-20 02:15:00'),
(8,'HH-20260120-000008',12,'USD',40.00,5.00,0.00,0.00,45.00,'Card','TRX-RFD-30001','Refund demo','refunded','refunded','Buyer Five','+8801700000012','Dhaka','BD','', '2026-01-20 03:00:00',NULL,1,'2026-01-20 03:20:00');

-- --------------------------
-- Order items (tie orders to sellers for risk computation)
--  - Seller 8 appears in 3 cancelled orders -> high_cancel_sellers
--  - Seller 9 appears in 4 total orders with 1 refunded -> high_refund_sellers (>=0.25 with total>=4)
--  - Seller 7 has >=10 qty and is not approved -> unverified_high_volume
-- --------------------------
INSERT IGNORE INTO `order_items` (
  `id`,`order_id`,`product_id`,`seller_id`,`title`,`image_url`,`unit_price`,`qty`,`line_total`
) VALUES
(10,3,'p3',7,'Boutique Item A','/uploads/products/p3_main.jpg',10.00,5,50.00),
(11,4,'p4',7,'Boutique Item B','/uploads/products/p4_main.jpg',10.00,5,50.00),
(12,5,'p5',8,'Leather Wallet','/uploads/products/p5_main.jpg',15.00,1,15.00),
(13,6,'p5',8,'Leather Wallet','/uploads/products/p5_main.jpg',16.00,1,16.00),
(14,7,'p5',8,'Leather Wallet','/uploads/products/p5_main.jpg',17.00,1,17.00),
(15,3,'p6',9,'Silver Ring','/uploads/products/p6_main.jpg',12.00,1,12.00),
(16,4,'p6',9,'Silver Ring','/uploads/products/p6_main.jpg',12.00,1,12.00),
(17,8,'p6',9,'Silver Ring','/uploads/products/p6_main.jpg',40.00,1,40.00),
(18,2,'p6',9,'Silver Ring','/uploads/products/p6_main.jpg',18.50,1,18.50);

-- --------------------------
-- Payouts (ledger uses payouts) - ensure at least 5 rows total
-- --------------------------
INSERT IGNORE INTO payouts (
  id,
  order_id,
  seller_id,
  gross_amount,
  commission_amount,
  net_payable,
  status,
  payout_ref,
  payout_method,
  paid_at,
  created_at
)
VALUES
(3,3,7,30.00,3.00,27.00,'pending','PAYOUT-DEMO-0003','bKash',NULL,'2026-01-20 01:15:00'),
(4,5,8,15.00,1.50,13.50,'blocked','PAYOUT-DEMO-0004','Nagad',NULL,'2026-01-20 02:20:00'),
(5,8,9,40.00,4.00,36.00,'paid','PAYOUT-DEMO-0005','Bank','2026-01-20 03:30:00','2026-01-20 03:30:00');



-- --------------------------
-- Support inbox demo conversations (buyer_support + seller_support)
-- Ensure at least 5 support conversations and messages with admin replies
-- --------------------------
INSERT IGNORE INTO `conversations` (
  `id`,`type`,`order_id`,`buyer_id`,`seller_id`,`status`,`priority`,`last_message_at`,`created_at`
) VALUES
(3,'buyer_support',NULL,10,1,'open','normal','2026-01-20 04:00:00','2026-01-20 04:00:00'),
(4,'buyer_support',NULL,11,1,'open','high','2026-01-20 04:05:00','2026-01-20 04:05:00'),
(5,'buyer_support',NULL,12,1,'closed','normal','2026-01-20 04:10:00','2026-01-20 04:10:00'),
(6,'seller_support',NULL,1,7,'open','normal','2026-01-20 04:15:00','2026-01-20 04:15:00'),
(7,'seller_support',NULL,1,8,'open','normal','2026-01-20 04:20:00','2026-01-20 04:20:00');

INSERT IGNORE INTO `messages` (`id`,`conversation_id`,`sender_role`,`sender_id`,`message_text`,`status`,`created_at`) VALUES
(10,3,'buyer',10,'Hello support, my order status is confusing.','seen','2026-01-20 04:00:10'),
(11,3,'admin',1,'Thanks! We checked—your order is on the way.','sent','2026-01-20 04:01:00'),
(12,4,'buyer',11,'Payment verified but not updated.','seen','2026-01-20 04:05:10'),
(13,4,'admin',1,'We updated the payment status. Please refresh.','sent','2026-01-20 04:06:00'),
(14,5,'buyer',12,'I want to change delivery phone number.','seen','2026-01-20 04:10:10'),
(15,5,'admin',1,'Done. Phone number updated.','sent','2026-01-20 04:11:00'),
(16,6,'seller',7,'Support: my payout method update is pending.','seen','2026-01-20 04:15:10'),
(17,6,'admin',1,'We have received it—reviewing shortly.','sent','2026-01-20 04:16:00'),
(18,7,'seller',8,'Support: KYC rejected, what should I do?','seen','2026-01-20 04:20:10'),
(19,7,'admin',1,'Please resubmit a clear NID photo and a selfie.','sent','2026-01-20 04:21:00');

-- keep last_message_at roughly consistent (optional)
UPDATE `conversations` SET last_message_at='2026-01-20 04:01:00' WHERE id=3;
UPDATE `conversations` SET last_message_at='2026-01-20 04:06:00' WHERE id=4;
UPDATE `conversations` SET last_message_at='2026-01-20 04:11:00' WHERE id=5;
UPDATE `conversations` SET last_message_at='2026-01-20 04:16:00' WHERE id=6;
UPDATE `conversations` SET last_message_at='2026-01-20 04:21:00' WHERE id=7;

-- ============================================================
SET FOREIGN_KEY_CHECKS=1;
-- End of DEMO DATA PACK

-- =====================================================
-- GI EXTENSIONS (RUN AFTER IMPORT)
-- =====================================================

CREATE TABLE IF NOT EXISTS `gi_authorities` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `name` VARCHAR(255) NOT NULL,
  `website` VARCHAR(255) DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gi_regions` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `authority_id` INT NOT NULL,
  `slug` VARCHAR(120) NOT NULL UNIQUE,
  `name` VARCHAR(255) NOT NULL,
  `signature_product` VARCHAR(255) DEFAULT NULL,
  `gi_registry_hint` VARCHAR(255) DEFAULT NULL,
  `shipping_note` VARCHAR(255) DEFAULT NULL,
  `map_x` INT DEFAULT 50,
  `map_y` INT DEFAULT 50,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `fk_gi_regions_authority` FOREIGN KEY (`authority_id`) REFERENCES `gi_authorities`(`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `gi_certificates` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `region_id` INT NOT NULL,
  `certificate_no` VARCHAR(120) NOT NULL UNIQUE,
  `issued_year` YEAR NOT NULL,
  `authority_name` VARCHAR(255) NOT NULL,
  `note` VARCHAR(255) DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT `fk_gi_cert_region` FOREIGN KEY (`region_id`) REFERENCES `gi_regions`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


INSERT INTO `gi_authorities` (`name`,`website`) VALUES
('Department of Patents, Designs and Trademarks (DPDT)','https://dpdt.gov.bd/'),
('Bangladesh Small and Cottage Industries Corporation (BSCIC)','https://bscic.gov.bd/')
ON DUPLICATE KEY UPDATE website=VALUES(website);

INSERT INTO `gi_regions` (`authority_id`,`slug`,`name`,`signature_product`,`gi_registry_hint`,`shipping_note`,`map_x`,`map_y`) VALUES
(1,'jamdani-narayanganj','Narayanganj (Jamdani)','Jamdani Saree','GI registered under DPDT','Export eligible (textile compliance)',35,45),
(1,'rajshahi-silk','Rajshahi (Silk)','Rajshahi Silk','GI registered under DPDT','Humidity-safe packaging recommended',55,38),
(1,'bogura-doi','Bogura (Doi)','Bogura Doi','GI registered under DPDT','Restricted: chilled shipping only',48,58),
(2,'khulna-nakshi-kantha','Khulna (Nakshi Kantha)','Nakshi Kantha','Craft registry: BSCIC aligned','Export eligible (craft declaration)',28,62)
ON DUPLICATE KEY UPDATE name=VALUES(name);

INSERT INTO `gi_certificates` (`region_id`,`certificate_no`,`issued_year`,`authority_name`,`note`)
SELECT r.id, 'BD-GI-JAM-2016-001', 2016, 'DPDT', 'Authentic Jamdani provenance certificate'
FROM gi_regions r WHERE r.slug='jamdani-narayanganj'
ON DUPLICATE KEY UPDATE note=VALUES(note);

INSERT INTO `gi_certificates` (`region_id`,`certificate_no`,`issued_year`,`authority_name`,`note`)
SELECT r.id, 'BD-GI-SIL-2018-014', 2018, 'DPDT', 'Silk origin and quality compliance certificate'
FROM gi_regions r WHERE r.slug='rajshahi-silk'
ON DUPLICATE KEY UPDATE note=VALUES(note);

INSERT INTO `gi_certificates` (`region_id`,`certificate_no`,`issued_year`,`authority_name`,`note`)
SELECT r.id, 'BD-GI-DOI-2017-005', 2017, 'DPDT', 'Dairy GI certificate; chilled logistics note'
FROM gi_regions r WHERE r.slug='bogura-doi'
ON DUPLICATE KEY UPDATE note=VALUES(note);

INSERT INTO `gi_certificates` (`region_id`,`certificate_no`,`issued_year`,`authority_name`,`note`)
SELECT r.id, 'BD-CR-KAN-2015-022', 2015, 'BSCIC', 'Craft registry certificate for Nakshi Kantha'
FROM gi_regions r WHERE r.slug='khulna-nakshi-kantha'
ON DUPLICATE KEY UPDATE note=VALUES(note);



-- ==========================================================
-- Homepage CMS (DB-driven 14 sections)
-- ==========================================================

CREATE TABLE IF NOT EXISTS `homepage_sections` (
  `id` int NOT NULL AUTO_INCREMENT,
  `key` varchar(64) NOT NULL,
  `title` varchar(200) DEFAULT NULL,
  `subtitle` varchar(400) DEFAULT NULL,
  `kicker` varchar(120) DEFAULT NULL,
  `sort_order` int NOT NULL DEFAULT 0,
  `is_active` tinyint(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_homepage_sections_key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `homepage_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `section_key` varchar(64) NOT NULL,
  `label` varchar(200) DEFAULT NULL,
  `description` varchar(600) DEFAULT NULL,
  `value` varchar(120) DEFAULT NULL,
  `link_url` varchar(255) DEFAULT NULL,
  `cta_label` varchar(80) DEFAULT NULL,
  `is_primary` tinyint(1) NOT NULL DEFAULT 0,
  `meta_json` text,
  `sort_order` int NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_homepage_items_section` (`section_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- Seller profile extensions for artisan spotlight (safe add)
DROP PROCEDURE IF EXISTS add_col_if_missing;

DELIMITER $$
CREATE PROCEDURE add_col_if_missing(
    IN tbl VARCHAR(64),
    IN col VARCHAR(64),
    IN coldef TEXT
)
BEGIN
    IF NOT EXISTS(
        SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = tbl
          AND COLUMN_NAME = col
    ) THEN
        SET @s = CONCAT('ALTER TABLE `', tbl, '` ADD COLUMN `', col, '` ', coldef);
        PREPARE stmt FROM @s;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END$$
DELIMITER ;

CALL add_col_if_missing('seller_profiles','region_slug','varchar(80) DEFAULT NULL');
CALL add_col_if_missing('seller_profiles','craft_type','varchar(120) DEFAULT NULL');
CALL add_col_if_missing('seller_profiles','story','text DEFAULT NULL');
CALL add_col_if_missing('seller_profiles','image_url','varchar(255) DEFAULT NULL');
CALL add_col_if_missing('seller_profiles','is_featured','tinyint(1) NOT NULL DEFAULT 0');

DROP PROCEDURE IF EXISTS add_col_if_missing;



-- Seed: homepage sections
INSERT IGNORE INTO homepage_sections (`key`, title, subtitle, kicker, sort_order, is_active) VALUES
('gateway','Bangladesh GI marketplace—verified, calm, export-aware.','Browse by origin, verify authenticity, and purchase with confidence.','Geographical Indication (GI)',1,1),
('trust_signals',NULL,NULL,NULL,2,1),
('origin_map','Origin discovery','Explore GI regions and their signature crafts.','Bangladesh GI Map',3,1),
('browse_hub','Structured browse','Browse with GI logic: region, type, eligibility, verified-only.','Browse',4,1),
('heritage_stats','Live heritage statistics','A live view of artisans, origins, and verified inventory.','Live',5,1),
('certified_gallery','Certified product gallery','Admin-approved, GI-badged products with shipping eligibility.','Curated',6,1),
('flash_sale','Limited heritage offer','Short, respectful discounts tied to festivals or artisan support.','Time-window',7,1),
('heritage_journey','How GI verification works','From raw material to certification to your doorstep.','Process',8,1),
('artisan_spotlight','Artisan spotlight','A single story—region, craft, and a voice from the maker.','Featured',9,1),
('auth_check','Authenticity check','Verify a GI or product code before you buy.','Verification',10,1),
('certificate_wall','Certificate wall','GI certificates, authorities, and issuance years.','Documentation',11,1),
('gift_recommender','Smart gift recommender','Pick an occasion, budget, and shipping preference.','Gifts',12,1),
('heritage_commitment','Heritage commitment','Our platform pledge: authenticity, respect, compliance.','Pledge',13,1),
('seasonal_mode','Seasonal mode','Toggle festival mode without changing brand calm.','Theme',14,1);

-- Seed: hero CTAs + aside stats (meta.kind)
INSERT INTO homepage_items (section_key,label,description,value,link_url,cta_label,is_primary,meta_json,sort_order) VALUES
('gateway','Explore by Origin',NULL,NULL,'#origin-map',NULL,1,'{"kind":"cta"}',1),
('gateway','Verify Authenticity',NULL,NULL,'#auth-check',NULL,0,'{"kind":"cta"}',2),
('gateway','Regions indexed',NULL,'All verified origins',NULL,NULL,0,'{"kind":"aside"}',10),
('gateway','Certificate-linked',NULL,'Authority references',NULL,NULL,0,'{"kind":"aside"}',11),
('gateway','Export-aware',NULL,'Eligibility visible',NULL,NULL,0,'{"kind":"aside"}',12);

-- Seed: trust signals
INSERT INTO homepage_items (section_key,label,description,meta_json,sort_order) VALUES
('trust_signals','GI verified',NULL,'{}',1),
('trust_signals','Artisan-led',NULL,'{}',2),
('trust_signals','Export rules enforced',NULL,'{}',3),
('trust_signals','Certificate-linked',NULL,'{}',4),
('trust_signals','Secure access',NULL,'{}',5);

-- Seed: browse hub tiles
INSERT INTO homepage_items (section_key,label,description,link_url,cta_label,is_primary,meta_json,sort_order) VALUES
('browse_hub','Browse by Region','Discover GI origin clusters and signature products.','/shop?view=region','Browse',1,'{}',1),
('browse_hub','Browse by Product Type','Filter by craft and category (jute, pottery, textile).','/shop?view=type','Browse','0','{}',2),
('browse_hub','Browse by Shipping Eligibility','See what can ship locally or internationally.','/shop?ship=1','Browse','0','{}',3),
('browse_hub','Browse GI-verified only','Only admin-verified GI inventory.','/shop?gi=1','Browse','0','{}',4);

-- Seed: journey steps
INSERT INTO homepage_items (section_key,label,description,meta_json,sort_order) VALUES
('heritage_journey','Raw material','Local sourcing and tradition-based inputs.','{}',1),
('heritage_journey','Artisan','Maker identity and craft method recorded.','{}',2),
('heritage_journey','Certification','Authority-linked certificate reference.','{}',3),
('heritage_journey','Product','GI badge + shipping eligibility visible.','{}',4),
('heritage_journey','Delivery','Tracking, packaging, export rules respected.','{}',5);

-- Seed: flash reason
INSERT INTO homepage_items (section_key,label,description,meta_json,sort_order) VALUES
('flash_sale','Festival support','Discount is tied to seasonal artisan support and fair demand.','{"kind":"reason"}',1);

-- Seed: commitment cards
INSERT INTO homepage_items (section_key,label,description,meta_json,sort_order) VALUES
('heritage_commitment','Authenticity pledge','Every GI badge is traceable and authority-linked.','{}',1),
('heritage_commitment','Artisan respect','Transparent margins, fair representation, maker-first stories.','{}',2),
('heritage_commitment','GI law compliance','Listings follow GI and export eligibility rules.','{}',3);

-- Seed: gift recommender options + items
INSERT INTO homepage_items (section_key,label,description,link_url,cta_label,is_primary,meta_json,sort_order) VALUES
('gift_recommender','Wedding','Occasion option',NULL,NULL,0,'{"kind":"option","type":"occasion","value":"wedding"}',1),
('gift_recommender','Housewarming','Occasion option',NULL,NULL,0,'{"kind":"option","type":"occasion","value":"housewarming"}',2),
('gift_recommender','Corporate','Occasion option',NULL,NULL,0,'{"kind":"option","type":"occasion","value":"corporate"}',3),
('gift_recommender','Under $25','Budget option',NULL,NULL,0,'{"kind":"option","type":"budget","value":"b1"}',10),
('gift_recommender','$25–$60','Budget option',NULL,NULL,0,'{"kind":"option","type":"budget","value":"b2"}',11),
('gift_recommender','$60+','Budget option',NULL,NULL,0,'{"kind":"option","type":"budget","value":"b3"}',12),
('gift_recommender','Local shipping','Shipping option',NULL,NULL,0,'{"kind":"option","type":"shipping","value":"local"}',20),
('gift_recommender','International shipping','Shipping option',NULL,NULL,0,'{"kind":"option","type":"shipping","value":"intl"}',21),

('gift_recommender','Jute craft set','GI-aligned, export-friendly packaging.','/shop?gi=1&cat=jute','View',1,'{"kind":"gift_item","occasion":"housewarming","budget":"b2","shipping":"local"}',101),
('gift_recommender','Pottery for table','Authentic craft, calm gifting.','/shop?gi=1&cat=pottery','View',0,'{"kind":"gift_item","occasion":"wedding","budget":"b3","shipping":"local"}',102),
('gift_recommender','Textile keepsake','Heritage textile from verified origin.','/shop?gi=1&cat=textile','View',0,'{"kind":"gift_item","occasion":"corporate","budget":"b2","shipping":"intl"}',103),
('gift_recommender','Tea + sweet hamper','Seasonal, export-aware gift.','/shop?gi=1&cat=food','View',0,'{"kind":"gift_item","occasion":"housewarming","budget":"b1","shipping":"intl"}',104);


-- Seed: featured artisan spotlight (pick one existing seller profile)
UPDATE seller_profiles
SET region_slug = COALESCE(region_slug,'khulna'),
    craft_type = COALESCE(craft_type,'Pottery'),
    story = COALESCE(story,'We shape clay using local techniques passed down through generations. Each piece is fired in small batches and inspected for export-safe finishing.'),
    image_url = COALESCE(image_url, shop_banner_url),
    is_featured = 1
WHERE id = 1;

-- Seed: seasonal mode content
INSERT INTO homepage_items (section_key,label,description,meta_json,sort_order) VALUES
('seasonal_mode','Festival mode','Switch between Default and Festival tone without changing layout.','{"kind":"season","field":"card"}',1),
('seasonal_mode','Tip','Use festival mode for Eid, Pohela Boishakh, Victory Day, or artisan fairs.','{"kind":"season","field":"tip"}',2),
('seasonal_mode','Toggle festival mode','ARIA label for toggle','{"kind":"season","field":"toggle_aria"}',3);
