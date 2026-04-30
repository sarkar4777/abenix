package com.abenix.claimsiq.domain;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface ClaimRepository extends JpaRepository<Claim, UUID> {
    List<Claim> findTop200ByOrderByCreatedAtDesc();
    List<Claim> findByStatusOrderByCreatedAtDesc(String status);
}
