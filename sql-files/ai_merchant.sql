--
-- AI negotiating merchant (npc/custom/ai/ai_merchant.txt + tools/ai_merchant/agent.py)
-- One row per negotiation round. The NPC inserts a 'pending' row, the agent answers it.
--

CREATE TABLE IF NOT EXISTS `ai_merchant_turn` (
  `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
  `session_id` int(11) unsigned NOT NULL DEFAULT '0',
  `char_id` int(11) unsigned NOT NULL,
  `char_name` varchar(30) NOT NULL DEFAULT '',
  `item_id` int(10) unsigned NOT NULL,
  `item_name` varchar(50) NOT NULL DEFAULT '',
  `amount` smallint(5) unsigned NOT NULL,
  `list_price` int(11) unsigned NOT NULL,
  `floor_price` int(11) unsigned NOT NULL,
  `current_price` int(11) unsigned NOT NULL,
  `reputation` tinyint(3) unsigned NOT NULL DEFAULT '0',
  `round` tinyint(3) unsigned NOT NULL,
  `max_rounds` tinyint(3) unsigned NOT NULL,
  `player_message` varchar(255) NOT NULL DEFAULT '',
  `status` enum('pending','processing','done','error','expired') NOT NULL DEFAULT 'pending',
  `npc_reply` varchar(255) DEFAULT NULL,
  `offer_price` int(11) unsigned DEFAULT NULL,
  `mood` varchar(16) DEFAULT NULL,
  `outcome` enum('bought','declined') DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `answered_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `status` (`status`),
  KEY `session_id` (`session_id`),
  KEY `char_id` (`char_id`)
) ENGINE=MyISAM;
