-- ============================================================================
-- Smart Campus: Equipment Initial Inventory Seed Data (DEMO QUANTITIES)
-- Central collection and return location: Campus Gym
-- Note: These quantities are illustrative demo figures. Administrators can
-- adjust physical counts through the Inventory Management portal.
-- ============================================================================

INSERT INTO equipment_items (item_code, item_name, category, description, unit, total_quantity, damaged_quantity, maintenance_quantity, lost_quantity, location, is_active)
VALUES
-- Sports Equipment
('SPT-BAD-01', 'Badminton Racket', 'Sports', 'Lightweight carbon composite badminton racket for recreational and tournament play', 'Piece', 20, 0, 0, 0, 'Gym', 1),
('SPT-SHT-01', 'Badminton Shuttlecock', 'Sports', 'Standard nylon feather badminton shuttlecocks (tube of pieces)', 'Piece', 100, 0, 0, 0, 'Gym', 1),
('SPT-FTB-01', 'Football', 'Sports', 'Size 5 professional match/training football', 'Piece', 10, 0, 0, 0, 'Gym', 1),
('SPT-BSK-01', 'Basketball', 'Sports', 'Size 7 indoor/outdoor composite leather basketball', 'Piece', 10, 0, 0, 0, 'Gym', 1),
('SPT-VLB-01', 'Volleyball', 'Sports', 'Soft-touch synthetic leather official volleyball', 'Piece', 10, 0, 0, 0, 'Gym', 1),
('SPT-CKB-01', 'Cricket Bat', 'Sports', 'Kashmir willow full-size cricket bat with rubber grip', 'Piece', 10, 0, 0, 0, 'Gym', 1),
('SPT-CBL-01', 'Cricket Ball', 'Sports', 'Heavy leather/cork seam cricket ball for matches', 'Piece', 30, 0, 0, 0, 'Gym', 1),
('SPT-CKS-01', 'Cricket Stumps', 'Sports', 'Wooden spring-loaded cricket stumps with bails', 'Set', 5, 0, 0, 0, 'Gym', 1),
('SPT-TTB-01', 'Table Tennis Bat', 'Sports', 'Competition rubber-padded table tennis paddle', 'Piece', 12, 0, 0, 0, 'Gym', 1),
('SPT-TTL-01', 'Table Tennis Ball', 'Sports', '3-star 40mm competition table tennis balls', 'Piece', 50, 0, 0, 0, 'Gym', 1),
('SPT-TRK-01', 'Tennis Racket', 'Sports', 'Aluminium composite lawn tennis racket with cover', 'Piece', 6, 0, 0, 0, 'Gym', 1),
('SPT-TBL-01', 'Tennis Ball', 'Sports', 'Pressurised high-durability yellow lawn tennis balls', 'Piece', 24, 0, 0, 0, 'Gym', 1),
('SPT-CHS-01', 'Chess Set', 'Sports', 'Tournament regulation weighted chess pieces with rollout vinyl board', 'Set', 10, 0, 0, 0, 'Gym', 1),
('SPT-CRM-01', 'Carrom Board', 'Sports', 'Standard 32x32 inch wooden carrom board with coins and striker', 'Piece', 4, 0, 0, 0, 'Gym', 1),
('SPT-SKP-01', 'Skipping Rope', 'Sports', 'High-speed bearing adjustable fitness jump rope', 'Piece', 20, 0, 0, 0, 'Gym', 1),
('SPT-CON-01', 'Sports Cones', 'Sports', 'High-visibility agility and drill marking cones', 'Piece', 30, 0, 0, 0, 'Gym', 1),
('SPT-BIB-01', 'Training Bibs', 'Sports', 'Breathable mesh coloured scrimmage team vests', 'Piece', 40, 0, 0, 0, 'Gym', 1),
('SPT-PMP-01', 'Hand Pump', 'Sports', 'Dual-action ball inflation pump with metal needle', 'Piece', 3, 0, 0, 0, 'Gym', 1),

-- Electronic and Presentation Equipment
('AV-PRJ-01', 'Projector', 'Audio/Visual', 'Full HD 1080p 4000-lumens multimedia digital projector', 'Piece', 6, 0, 0, 0, 'Gym', 1),
('ACC-HDM-01', 'HDMI Cable', 'Accessories', 'High-speed 4K 5-metre braided gold-plated HDMI cable', 'Piece', 15, 0, 0, 0, 'Gym', 1),
('ACC-VGA-01', 'VGA Cable', 'Accessories', 'Standard 3-metre male-to-male video graphics array cable', 'Piece', 5, 0, 0, 0, 'Gym', 1),
('AV-WMC-01', 'Wireless Microphone', 'Audio/Visual', 'UHF handheld wireless microphone with rechargeable receiver', 'Piece', 8, 0, 0, 0, 'Gym', 1),
('AV-MIC-01', 'Wired Microphone', 'Audio/Visual', 'Dynamic cardioid vocal microphone with 6m XLR-to-jack cable', 'Piece', 8, 0, 0, 0, 'Gym', 1),
('AV-SPK-01', 'Portable Speaker', 'Audio/Visual', 'Rechargeable Bluetooth portable party speaker with mic input', 'Piece', 5, 0, 0, 0, 'Gym', 1),
('AV-PAS-01', 'PA Speaker', 'Audio/Visual', 'Heavy-duty 400W powered auditorium public address active speaker', 'Piece', 4, 0, 0, 0, 'Gym', 1),
('ELC-EXT-01', 'Extension Board', 'Electronics', 'Heavy-duty 4-socket 10A spike guard with 5m copper cord', 'Piece', 15, 0, 0, 0, 'Gym', 1),
('ELC-PWS-01', 'Power Strip', 'Electronics', '6-outlet universal power strip with individual switches and surge protection', 'Piece', 10, 0, 0, 0, 'Gym', 1),
('ELC-LPT-01', 'Laser Pointer', 'Electronics', 'Red-beam presentation pointer with integrated USB dongle', 'Piece', 6, 0, 0, 0, 'Gym', 1),
('ELC-CLK-01', 'Presentation Clicker', 'Electronics', 'Wireless slide advancer with forward, backward and black screen controls', 'Piece', 6, 0, 0, 0, 'Gym', 1),
('IT-CAM-01', 'Webcam', 'IT', '1080p widescreen USB streaming webcam with dual noise-cancelling mics', 'Piece', 5, 0, 0, 0, 'Gym', 1),
('ACC-TRP-01', 'Camera Tripod', 'Accessories', 'Adjustable 60-inch aluminium photography and video camera tripod', 'Piece', 4, 0, 0, 0, 'Gym', 1),
('IT-LAP-01', 'Laptop', 'IT', 'Campus event loaner Intel Core i5 laptop with HDMI output and presentation software', 'Piece', 5, 0, 0, 0, 'Gym', 1)
ON DUPLICATE KEY UPDATE
    item_name = VALUES(item_name),
    category = VALUES(category),
    description = VALUES(description),
    unit = VALUES(unit),
    location = VALUES(location);
